"""월별 리밸런싱 백테스트 엔진.

- 신호(SMA·12개월 수익률·52주 고점)는 배당을 뺀 가격(Close)으로 계산한다(전략 명세와 같음).
- 수익률은 배당을 다시 넣은 가격(Adj Close)으로 계산한다(실제 계좌 수익에 가까움).
- 매달 말 전략이 목표 비중을 내면 그 비중으로 다음 달을 보낸다. None을 내면
  지난달 비중이 가격 변동대로 흘러간(drift) 상태를 그대로 둔다.
- 거래 비용: 바뀐 비중(회전율)의 COST만큼 뺀다. 세금은 넣지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent / "data"
COST = 0.001  # 회전율 1당 0.1%
CASH = "CASH"


@dataclass
class Market:
    """월말 기준 표. 행=월말, 열=자산."""

    close: pd.DataFrame          # 월말 종가(배당 제외)
    total: pd.DataFrame          # 월말 총수익 지수(배당 포함)
    high52: pd.DataFrame         # 월말 기준 52주 최고 종가
    extra: dict = field(default_factory=dict)

    def ret(self) -> pd.DataFrame:
        return self.total.pct_change()

    def sma(self, n: int = 10) -> pd.DataFrame:
        return self.close.rolling(n).mean()

    def mom(self, months: int = 12) -> pd.DataFrame:
        return self.close / self.close.shift(months) - 1

    def mom_total(self, months: int) -> pd.DataFrame:
        return self.total / self.total.shift(months) - 1

    def w13612(self) -> pd.DataFrame:
        t = self.total
        return 12 * (t / t.shift(1) - 1) + 4 * (t / t.shift(3) - 1) + 2 * (t / t.shift(6) - 1) + (t / t.shift(12) - 1)

    def drawdown52(self) -> pd.DataFrame:
        return self.close / self.high52 - 1


Strategy = Callable[[pd.Timestamp, "Context"], "dict | None"]


@dataclass
class Context:
    m: Market
    i: int                       # 현재 월말의 위치
    weights: dict                # 지난 리밸런싱 뒤 흘러간 현재 비중
    state: dict

    @property
    def date(self) -> pd.Timestamp:
        return self.m.close.index[self.i]

    def val(self, frame: pd.DataFrame, col: str) -> float:
        return float(frame[col].iloc[self.i])


def run(strategy: Strategy, m: Market, start: str, end: str | None = None, cost: float = COST) -> pd.DataFrame:
    """월별 수익률과 비중 기록을 돌려준다."""
    rets = m.ret()
    idx = m.close.index
    pos = [k for k, d in enumerate(idx) if d >= pd.Timestamp(start) and (end is None or d <= pd.Timestamp(end))]
    weights: dict = {CASH: 1.0}
    state: dict = {}
    out = []
    for a, b in zip(pos[:-1], pos[1:]):
        ctx = Context(m, a, dict(weights), state)
        target = strategy(idx[a], ctx)
        new = dict(weights) if target is None else _norm(target)
        turnover = sum(abs(new.get(k, 0) - weights.get(k, 0)) for k in set(new) | set(weights)) / 2
        if not out:
            turnover = 0.0  # 첫 매수는 비용에서 뺀다(비교를 공정하게)
        r = {k: float(rets[k].iloc[b]) for k in new if new[k]}
        if any(np.isnan(v) for v in r.values()):
            raise ValueError(f"{idx[b].date()} 수익률 없음: {[k for k, v in r.items() if np.isnan(v)]}")
        port = sum(new[k] * r[k] for k in r) - cost * turnover * 2
        grown = {k: new[k] * (1 + r.get(k, 0)) for k in new if new[k]}
        tot = sum(grown.values())
        weights = {k: v / tot for k, v in grown.items()}
        out.append({"date": idx[b], "ret": port, "turnover": turnover, "weights": new})
    return pd.DataFrame(out).set_index("date")


def _norm(w: dict) -> dict:
    w = {k: float(v) for k, v in w.items() if v and v > 1e-12}
    s = sum(w.values())
    if s <= 0:
        return {CASH: 1.0}
    return {k: v / s for k, v in w.items()}


def stats(res: pd.DataFrame, cash: pd.Series | None = None) -> dict:
    r = res["ret"]
    n = len(r)
    curve = (1 + r).cumprod()
    years = n / 12
    cagr = curve.iloc[-1] ** (1 / years) - 1
    vol = r.std() * np.sqrt(12)
    dd = curve / curve.cummax() - 1
    mdd = dd.min()
    excess = r - (cash.reindex(r.index).fillna(0) if cash is not None else 0)
    sharpe = excess.mean() / r.std() * np.sqrt(12) if r.std() > 0 else np.nan
    down = r[r < 0]
    sortino = excess.mean() / np.sqrt((down ** 2).sum() / n) * np.sqrt(12) if len(down) else np.nan
    yearly = (1 + r).groupby(r.index.year).prod() - 1
    # 가장 긴 고점 회복 기간(개월)
    under, longest = 0, 0
    for v in dd:
        under = under + 1 if v < 0 else 0
        longest = max(longest, under)
    return {
        "CAGR": cagr, "변동성": vol, "MDD": mdd, "샤프": sharpe, "소르티노": sortino,
        "최악의 해": yearly.min(), "최고의 해": yearly.max(), "MAR": cagr / abs(mdd) if mdd < 0 else np.nan,
        "최장 회복(개월)": longest, "연 회전율": res["turnover"].sum() / years,
        "시작": r.index[0].strftime("%Y-%m"), "끝": r.index[-1].strftime("%Y-%m"),
    }


def yearly(res: pd.DataFrame) -> pd.Series:
    r = res["ret"]
    return (1 + r).groupby(r.index.year).prod() - 1


# ---------------------------------------------------------------- 자료 준비

def load_daily(data_dir: Path = DATA_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    close = pd.read_csv(data_dir / "close_daily.csv.gz", index_col=0, parse_dates=True)
    adj = pd.read_csv(data_dir / "adjclose_daily.csv.gz", index_col=0, parse_dates=True)
    return close.sort_index(), adj.sort_index()


def leveraged(daily_total: pd.Series, k: float, fee: float, cash_daily: pd.Series) -> pd.Series:
    """k배 일간 레버리지 합성: k×일수익 − (k−1)×차입 이자 − 보수."""
    r = daily_total.pct_change()
    c = cash_daily.reindex(r.index).ffill().fillna(0)
    lr = k * r - (k - 1) * c - fee / 252
    return (1 + lr.fillna(0)).cumprod() * 100


def build_market(close_d: pd.DataFrame, adj_d: pd.DataFrame, assets: dict, synth: dict | None = None,
                 fx: pd.Series | None = None, local: tuple = ()) -> Market:
    """assets: {이름: 열 이름 또는 [열 이름 목록(앞에서부터 우선, 없는 기간은 뒤 열로 이어 붙임)]}

    synth: {이름: pd.Series(일간 총수익 지수)} 합성 자산(레버리지 등). 종가=총수익 지수로 본다.
    fx: 주면 local에 없는 자산을 모두 이 환율(원/달러)로 곱해 원화 가격으로 바꾼다
        (국내 상장 환노출 ETF와 같은 효과). 환율이 없는 날은 빈칸이 된다.
    """
    cl, tr = {}, {}
    for name, cols in assets.items():
        cols = [cols] if isinstance(cols, str) else list(cols)
        c, t = _splice([close_d[x] for x in cols if x in close_d], [adj_d[x] for x in cols if x in adj_d])
        cl[name], tr[name] = c, t
    for name, s in (synth or {}).items():
        cl[name], tr[name] = s, s
    cl_d = pd.DataFrame(cl).sort_index()
    tr_d = pd.DataFrame(tr).sort_index()
    cl_d = cl_d.ffill(limit=5)
    tr_d = tr_d.ffill(limit=5)
    if fx is not None:
        rate = fx.reindex(cl_d.index).ffill(limit=5)
        for c in cl_d.columns:
            if c not in local:
                cl_d[c] = cl_d[c] * rate
                tr_d[c] = tr_d[c] * rate
    high = cl_d.rolling("365D", min_periods=200).max()
    me = cl_d.resample("ME").last().index
    def month_end(df: pd.DataFrame) -> pd.DataFrame:
        return df.resample("ME").last()
    return Market(month_end(cl_d), month_end(tr_d), month_end(high).reindex(me))


def _splice(closes: list[pd.Series], totals: list[pd.Series]) -> tuple[pd.Series, pd.Series]:
    """첫 번째 자료를 기준으로, 그 전 기간은 다음 자료의 수익률로 거꾸로 이어 붙인다."""
    c0, t0 = closes[0].dropna(), totals[0].dropna()
    for c1, t1 in zip(closes[1:], totals[1:]):
        c1, t1 = c1.dropna(), t1.dropna()
        if c1.empty:
            continue
        first = c0.index[0]
        before_c = c1[c1.index <= first]
        before_t = t1[t1.index <= first]
        if len(before_c) < 2:
            continue
        c0 = pd.concat([before_c.iloc[:-1] * (c0.iloc[0] / before_c.iloc[-1]), c0])
        t0 = pd.concat([before_t.iloc[:-1] * (t0.iloc[0] / before_t.iloc[-1]), t0])
    return c0, t0
