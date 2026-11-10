"""더 출렁이는 시장을 가정한 스트레스 시험: python -m backtest.stress 비중.json

1. 변동성 키우기: 현금을 뺀 모든 자산의 월수익을 평균은 그대로 두고 평균에서 벗어난 폭만 k배(1.25, 1.5)로 키운 뒤
   전략 신호까지 다시 계산한다.
2. 최근 시장 다시 섞기: 조합의 원화 월수익 중 최근 구간(2015~, 2020~)을 12개월 덩어리로 무작위로 이어 붙여
   20년 경로 5,000개를 만들고 최대 하락 분포를 본다.
3. 한 달 안의 급락: 매달 초 실제 보유 비중에 급락을 한 번에 넣어 그달 손실을 계산한다(월말 판단이라 피할 수 없음).
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from backtest import evaluate as E
from backtest.best_mix import seg_stats
from backtest.engine import CASH, Market, run
from backtest.mix2 import _extend
from backtest.run import END, prepare

CHOSEN = {
    "2027 확정 (GSM·DAA·S&P2배·S&P500+국내 절반 필터)": ("GSM 상위2+금·채권", "DAA", "S&P2배 SMA 추세", "S&P500 보유", "국내 주식 절반 필터"),
    "F1 (10-28 확정)": ("GSM 상위2+금·채권", "LAA 변형", "나스닥2배 SMA 추세", "국내 주식 보유", "S&P500 보유"),
    "b (연금 GSM 둘+듀얼)": ("GSM 상위2 현금없음", "GSM 상위2 현금없음", "나스닥2배 SMA 추세", "국내·미국 듀얼", "S&P500 보유"),
    "2026 조합": ("GSM 1위(2026)", "LAA 변형", "나스닥2배 단계(2026)", "국내 주식 보유", "SSO 단계(2026)"),
}
SAFE = {CASH, "BIL", "SHORTB"}


def scale_market(m: Market, k: float) -> Market:
    if k == 1:
        return m
    t = m.total.copy()
    c = m.close.copy()
    for col in t.columns:
        if col in SAFE:
            continue
        r = t[col].pct_change(fill_method=None)
        mu = r.mean()
        r2 = mu + k * (r - mu)
        first = t[col].first_valid_index()
        if first is None:
            continue
        new = (1 + r2.fillna(0)).cumprod() * t[col].loc[first]
        new[t[col].isna()] = np.nan
        ratio = c[col] / t[col]
        t[col] = new
        c[col] = new * ratio
    high = c.rolling(12, min_periods=1).max()
    return Market(close=c, total=t, high52=high, extra=m.extra)


def markets(k: float, info_cache: dict) -> dict:
    base = {"krw": _extend(prepare(krw=True), True), "usd": _extend(prepare(krw=False), False)}
    tick = pd.read_csv("backtest/data/tickers.csv")
    avail = set(tick.loc[tick["rows"] > 0, "ticker"])
    dom, info = E.domestic_market(base["krw"], base["usd"], avail)
    info_cache["info"] = info
    return {"krw": scale_market(base["krw"], k), "usd": scale_market(base["usd"], k), "dom": scale_market(dom, k)}


def port_returns(series, combo, w, key="krw") -> pd.Series:
    v = E.portfolio_paths(series, combo, w, key).sum(axis=1)
    r = v.pct_change()
    r.iloc[0] = v.iloc[0] - 1
    return r


def bootstrap_mdd(r: pd.Series, start: str, years=20, n=5000, block=12, seed=0) -> dict:
    x = r.loc[start:].values
    rng = np.random.default_rng(seed)
    months = years * 12
    nb = months // block
    starts = rng.integers(0, len(x) - block + 1, size=(n, nb))
    paths = np.stack([np.concatenate([x[s:s + block] for s in row]) for row in starts])
    _, mdd, _ = seg_stats(paths)
    return {"중간값": np.median(mdd), "나쁜 5%": np.quantile(mdd, .05), "-20% 넘을 확률": (mdd < -.20).mean()}


SHOCKS = {
    "2020형 급락 (주식 -25%, 국내 -30%, 2배 -50%, 금 -5%, 채권 +3~5%)": {
        "주식": -.25, "국내": -.30, "신흥국": -.28, "2배": -.50, "금": -.05, "10년채": .03, "장기채": .05},
    "2022형 동반 하락 (주식 -15%, 국내 -18%, 2배 -30%, 금 -8%, 10년채 -6%, 장기채 -12%)": {
        "주식": -.15, "국내": -.18, "신흥국": -.17, "2배": -.30, "금": -.08, "10년채": -.06, "장기채": -.12},
}
GROUP = {"SPX": "주식", "NDX": "주식", "WORLD": "주식", "EURO": "주식", "EFA": "주식", "SCHD": "주식", "SMALL": "주식",
         "EEM": "신흥국", "KOSPI": "국내", "SSO": "2배", "QLD": "2배", "GOLD": "금", "UST10": "10년채", "TLT": "장기채"}


def shock_losses(markets_, combo, w) -> dict:
    """매달 초 보유에 급락을 넣었을 때 전체 손실(금·별도 현금 포함)."""
    v = E.VARIANTS["기본"]
    menus = {"pen": E.P, "isa": {**E.P, **E.ISA_ONLY}}
    weights = {}
    for a, n in zip(E.ACC, combo):
        g = E.GRP[a]
        if g == "gen":
            fn, mk = E.GEN[n][1](v), markets_["krw"]
        else:
            fn, mk = menus[g][n][2](v), markets_["dom"]
        weights[a] = run(fn, mk, "2005-01-31", END)["weights"]
    out = {}
    for name, sh in SHOCKS.items():
        loss = []
        for d in weights["PEN_FREE"].index:
            tot = w["GOLD"] * sh["금"]
            for a in E.ACC:
                hold = weights[a].get(d, {})
                tot += w[a] * sum(x * sh.get(GROUP.get(k, ""), 0.0) for k, x in hold.items())
            loss.append(tot)
        s = pd.Series(loss, index=weights["PEN_FREE"].index)
        out[name] = {"가장 나쁜 달": s.min(), "중간값": s.median(), "마지막 달(2026-09 보유)": s.iloc[-1]}
    return out


def main(path: str) -> None:
    acc = json.loads(open(path, encoding="utf-8").read())
    tot = sum(acc.values())
    w = {k: v / tot for k, v in acc.items()}
    cache: dict = {}
    print("## 1. 변동성 키우기 (신호까지 다시 계산, 원화 2005~ / 방패 시험 달러 1997~)\n")
    rows = []
    keep = {}
    for k in (1.0, 1.25, 1.5):
        M = markets(k, cache)
        ser = E.account_series(M, cache["info"], "기본")
        for name, c in CHOSEN.items():
            rk = port_returns(ser, c, w, "krw")
            ru = port_returns(ser, c, w, "usd")
            cg, md, wo = seg_stats(rk.values[None, :])
            cu, mu, _ = seg_stats(ru.values[None, :])
            rows.append({"변동성": f"{k}배", "조합": name, "원화 연수익": cg[0], "원화 MDD": md[0], "최악 12개월": wo[0],
                         "달러 연수익": cu[0], "달러 MDD": mu[0]})
            if k == 1.0:
                keep[name] = rk
        if k == 1.0:
            M1 = M
    t = pd.DataFrame(rows)
    for c in ["원화 연수익", "원화 MDD", "최악 12개월", "달러 연수익", "달러 MDD"]:
        t[c] = t[c].map(lambda x: f"{x * 100:.1f}%")
    print(t.to_markdown(index=False))

    print("\n## 2. 최근 시장으로 다시 섞은 20년 경로 5,000개의 최대 하락 (12개월 덩어리)\n")
    rows = []
    for start in ("2015-01-01", "2020-01-01"):
        for name, r in keep.items():
            b = bootstrap_mdd(r, start)
            rows.append({"섞은 구간": f"{start[:4]}~2026", "조합": name, "MDD 중간값": f"{b['중간값'] * 100:.1f}%",
                         "MDD 나쁜 5%": f"{b['나쁜 5%'] * 100:.1f}%", "-20% 넘을 확률": f"{b['-20% 넘을 확률'] * 100:.0f}%"})
    print(pd.DataFrame(rows).to_markdown(index=False))

    print("\n## 3. 한 달 안에 급락이 오면 (매달 초 실제 보유 기준, 환율 도움 없음)\n")
    rows = []
    for name, c in CHOSEN.items():
        for sh, v in shock_losses(M1, c, w).items():
            rows.append({"조합": name, "급락": sh.split(" (")[0], **{k: f"{x * 100:.1f}%" for k, x in v.items()}})
    print(pd.DataFrame(rows).to_markdown(index=False))
    print("\n급락 가정:", {k: v for k, v in SHOCKS.items()})


if __name__ == "__main__":
    main(*sys.argv[1:])
