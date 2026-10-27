"""계좌 전체(여러 전략 합산) 백테스트: python -m backtest.portfolio 비중.json

비중.json 예: {"GSM": 10, "LAA": 20, "GOLD": 10, "ISA": 5, "SSO": 15, "EM": 25, "CASH": 15}
(금액이나 비율 아무거나. 실제 금액이 담긴 파일은 저장소에 올리지 않는다.)

계좌끼리는 돈을 옮기지 않으므로, 시작 비중으로 출발한 뒤 각 계좌가 따로 불어난다고 본다.
원화 기준(해외 자산은 원/달러 환산, 금 현물은 국제 금시세×환율, 일반계좌 1은 KODEX 200).
"""
from __future__ import annotations

import json
import sys

import pandas as pd

from backtest import strategies as S
from backtest.engine import CASH, run, stats
from backtest.run import END, crisis, fmt, prepare

START = "2005-01-31"  # 원/달러 자료로 원화 신호를 계산할 수 있는 첫 시점

SLEEVES = {
    "현재": {
        "GSM": S.gsm(),
        "LAA": S.laa_variant(),
        "SSO": S.ladder("SSO", "SPX_USD", .70, S.SSO_STEPS),
        "ISA": S.ladder("QLD", "NDX_USD", 0.0, S.ISA_STEPS),
    },
    "제안": {
        "GSM": S.gsm(),
        "LAA": S.laa_variant(),
        "SSO": S.ladder("SSO", "SPX_USD", .70, S.SSO_STEPS, sma_exit=True),
        "ISA": S.ladder("QLD", "NDX_USD", 0.0, S.ISA_STEPS, sma_sell=True),
    },
}
FIXED = {"GOLD": S.hold({"GOLD": 1}), "EM": S.hold({"KOSPI": 1}), "CASH": S.hold({CASH: 1})}


def combine(results: dict, weights: dict) -> pd.DataFrame:
    """계좌별 월수익률을 시작 비중대로 합친다(계좌 사이 리밸런싱 없음)."""
    total = sum(weights.values())
    w = {k: v / total for k, v in weights.items()}
    values = pd.DataFrame({k: w[k] * (1 + results[k]["ret"]).cumprod() for k in w})
    curve = values.sum(axis=1)
    ret = curve.pct_change()
    ret.iloc[0] = curve.iloc[0] - 1
    return pd.DataFrame({"ret": ret, "turnover": 0.0}), values.div(curve, axis=0)


def main(path: str, start: str = START) -> None:
    weights = json.loads(open(path, encoding="utf-8").read())
    m = prepare(krw=True)
    cash_r = m.ret()[CASH]
    rows, crises, shares = {}, {}, {}
    for label, sleeves in SLEEVES.items():
        res = {k: run(fn, m, start, END) for k, fn in {**sleeves, **FIXED}.items()}
        port, share = combine(res, weights)
        rows[f"전체 ({label} 규칙)"] = stats(port, cash_r)
        crises[f"전체 ({label} 규칙)"] = port
        shares[label] = share
        if label == "현재":
            for k, r in res.items():
                rows[f"  {k} 계좌만"] = stats(r, cash_r)
                crises[f"  {k} 계좌만"] = r
        else:
            for k in ("SSO", "ISA"):
                rows[f"  {k} 계좌만 (제안)"] = stats(res[k], cash_r)
                crises[f"  {k} 계좌만 (제안)"] = res[k]
    cols = ["CAGR", "변동성", "MDD", "샤프", "최악의 해", "최장 회복(개월)"]
    print(f"원화 기준 {start[:7]}~{END[:7]}\n")
    print(fmt(pd.DataFrame(rows).T[cols]).to_markdown())
    print()
    print(fmt(crisis(crises)).to_markdown())
    print("\n시작 비중 → 끝 비중(현재 규칙)")
    print((shares["현재"].iloc[[0, -1]].T * 100).round(1).to_markdown())


if __name__ == "__main__":
    main(*sys.argv[1:])
