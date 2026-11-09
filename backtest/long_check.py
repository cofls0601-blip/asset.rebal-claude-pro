"""2027 조합(F1)이 전체 자산 최대 하락 한도(-20%)를 지키는지 긴 기간으로 확인한다.

python -m backtest.long_check 비중.json

비중.json (저장소에 올리지 않는다): {"GSM": 금액, "LAA": 금액, "ISA": 금액, "EM": 금액, "GEN2": 금액, "GOLD": 금액, "CASH": 금액}

- 달러 기준 2000-01~: 닷컴 붕괴 포함. 2003년 이전 원/달러 자료가 없어 환율 효과는 뺐다.
  일반계좌 1(국내 주식)은 EWY(한국 주식 ETF, 달러), 상장 전 2000-01~04는 신흥국 주식 펀드(VEIEX)로 대신한다.
- 원화 기준 2005-01~: 2008 금융위기 포함. 일반계좌 1은 KODEX 200(그 전은 EWY×환율).
계좌 사이에는 돈을 옮기지 않는다. 세금은 넣지 않는다. 일반계좌 1의 실제 종목 구성(반도체 비중)은 반영하지 않는다.
"""
from __future__ import annotations

import json
import sys

import pandas as pd

from backtest import strategies as S
from backtest.engine import CASH, Market, build_market, run, stats
from backtest.portfolio import combine
from backtest.run import END, crisis, fmt, prepare

LIMIT = -0.20


def trend(asset: str, signal: str):
    """신호 지수가 10개월 SMA 위면 asset 100%, 아래면 현금 100% (2027 ISA)."""
    def strat(d, ctx):
        m = ctx.m
        return {asset: 1.0} if ctx.val(m.close, signal) > ctx.val(m.sma(10), signal) else {CASH: 1.0}
    return strat


def market(krw: bool) -> tuple[Market, str, str, str]:
    m = prepare(krw=krw)
    if krw:
        return m, "KOSPI", "SPX_USD", "NDX_USD"
    k = build_market(m.extra["close_d"], m.extra["adj_d"], {"KOREA": ["EWY", "VEIEX"]})
    m = Market(close=m.close.join(k.close), total=m.total.join(k.total), high52=m.high52.join(k.high52),
               extra=m.extra)
    return m, "KOREA", "SPX", "NDX"


def plans(korea: str, spx_sig: str, ndx_sig: str) -> dict:
    fixed = {"EM": S.hold({korea: 1}), "GOLD": S.hold({"GOLD": 1}), "CASH": S.hold({CASH: 1})}
    return {
        "2027 조합 (F1)": {
            "GSM": S.gsm(cands=("NDX", "SPX", "WORLD", "EURO", "GOLD", "UST10"), top=2),
            "LAA": S.laa_variant(),
            "ISA": trend("QLD", ndx_sig),
            "GEN2": S.hold({"SPX": 1}),
            **fixed,
        },
        "(비교) 2026 조합": {
            "GSM": S.gsm(),
            "LAA": S.laa_variant(),
            "ISA": S.ladder("QLD", ndx_sig, 0.0, S.ISA_STEPS),
            "GEN2": S.ladder("SSO", spx_sig, .70, S.SSO_STEPS),
            **fixed,
        },
    }


def drawdown_table(port: pd.DataFrame, top: int = 3) -> list[str]:
    curve = (1 + port["ret"]).cumprod()
    dd = curve / curve.cummax() - 1
    out, used = [], pd.Series(False, index=dd.index)
    for _ in range(top):
        cand = dd[~used]
        if cand.empty or cand.min() >= 0:
            break
        bottom = cand.idxmin()
        peak = curve[:bottom].idxmax()
        after = dd[bottom:]
        rec = after[after >= 0]
        end = rec.index[0] if len(rec) else None
        out.append(f"{peak:%Y-%m} 고점 → {bottom:%Y-%m} 바닥 {dd[bottom] * 100:.1f}%, "
                   + (f"{end:%Y-%m} 회복" if end is not None else "아직 회복 못 함"))
        used[peak:(end or dd.index[-1])] = True
    return out


def main(path: str) -> None:
    w = json.loads(open(path, encoding="utf-8").read())
    total = sum(w.values())
    print("계좌 비중: " + ", ".join(f"{k} {v / total * 100:.1f}%" for k, v in w.items()) + "\n")
    cols = ["CAGR", "변동성", "MDD", "최악의 해", "최장 회복(개월)"]
    for label, krw, start in [("달러 기준", False, "2000-01-31"), ("원화 기준", True, "2005-01-31")]:
        m, korea, spx_sig, ndx_sig = market(krw)
        cash_r = m.ret()[CASH]
        rows, ports, accts = {}, {}, {}
        for name, plan in plans(korea, spx_sig, ndx_sig).items():
            res = {k: run(fn, m, start, END) for k, fn in plan.items()}
            port = combine(res, w)[0]
            rows[name], ports[name] = stats(port, cash_r), port
            if name.startswith("2027"):
                accts = {f"  {k} 계좌만": stats(r, cash_r) for k, r in res.items()}
                f1 = port
        print(f"## {label} {start[:7]}~{END[:7]}\n")
        print(fmt(pd.DataFrame({**rows, **accts}).T[cols]).to_markdown())
        print()
        print(fmt(crisis(ports)).to_markdown())
        mdd = rows["2027 조합 (F1)"]["MDD"]
        print(f"\n한도 {LIMIT * 100:.0f}%: {'지킴' if mdd >= LIMIT else '넘음'} (F1 최대 하락 {mdd * 100:.1f}%)")
        print("F1 큰 하락: " + " / ".join(drawdown_table(f1)) + "\n")


if __name__ == "__main__":
    main(*sys.argv[1:])
