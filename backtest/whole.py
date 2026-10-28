"""전체 계좌 백테스트와 다른 자산배분 전략 비교: python -m backtest.whole 구성.json

구성.json (저장소에 올리지 않는다):
  {"accounts": {"GSM": 금액, "LAA": 금액, "GOLD": 금액, "ISA": 금액, "SSO": 금액, "EM": 금액, "CASH": 금액},
   "em_stocks": {"SAMSUNG": 비율, ...}, "em_cash_share": 0.15}
원화 기준. 계좌 사이에는 돈을 옮기지 않는다. 세금은 넣지 않는다(일반계좌 1만 근사 세후 줄을 따로 보여 준다).
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from backtest import strategies as S
from backtest.engine import CASH, run, stats
from backtest.portfolio import combine
from backtest.run import BENCH, END, KNOWN, crisis, fmt, prepare

START = "2007-03-31"  # HAA 등 비교 전략의 자산(원자재 등)이 모두 있는 시점
CATEGORY = {
    "KOSPI": "신흥국 주식", "SAMSUNG": "신흥국 주식", "HYNIX": "신흥국 주식", "HYUNDAI": "신흥국 주식",
    "IBK": "신흥국 주식", "TOP10": "신흥국 주식", "EEM": "신흥국 주식",
    "NDX": "선진국 주식", "SPX": "선진국 주식", "WORLD": "선진국 주식", "EURO": "선진국 주식", "EFA": "선진국 주식",
    "IWM": "선진국 주식", "EWJ": "선진국 주식", "SSO": "선진국 주식", "QLD": "선진국 주식", "REIT": "선진국 주식",
    "UST10": "선진국 채권", "TLT": "선진국 채권", "SHY": "선진국 채권", "AGG": "선진국 채권", "LQD": "선진국 채권",
    "HYG": "선진국 채권", "TIP": "선진국 채권", "KTB10": "신흥국 채권", "GOLD": "금", "DBC": "원자재", CASH: "현금",
}


def plans(cfg: dict) -> dict:
    em_cur = S.mix(cfg["em_stocks"], 1 - cfg["em_cash_share"])
    base = {
        "GSM": S.gsm(), "LAA": S.laa_variant(),
        "SSO": S.ladder("SSO", "SPX_USD", .70, S.SSO_STEPS),
        "ISA": S.ladder("QLD", "NDX_USD", 0.0, S.ISA_STEPS),
        "GOLD": S.hold({"GOLD": 1}), "CASH": S.hold({CASH: 1}), "EM": em_cur,
    }
    proposed_lev = {"SSO": S.ladder("SSO", "SPX_USD", .70, S.SSO_STEPS, sma_exit=True),
                    "ISA": S.ladder("QLD", "NDX_USD", 0.0, S.ISA_STEPS, sma_sell=True)}
    dual = S.relative_momentum(("KOSPI", "SPX"))
    return {
        "① 지금 그대로": base,
        "② 일반계좌1 = 국내·미국 듀얼 모멘텀": {**base, "EM": dual},
        "③ ② + SSO·ISA 제안 규칙": {**base, "EM": dual, **proposed_lev},
        "④ 일반계좌1 = 국내 주식 절반 필터": {**base, "EM": S.mix({"KOSPI": 1}, 1.0, "KOSPI", .5)},
        "⑤ 일반계좌1 그대로 + SSO·ISA 제안 규칙": {**base, **proposed_lev},
    }


ALTERNATIVES = {k: KNOWN[k] for k in ["HAA", "BAA-G12", "DAA-G12", "VAA-G4", "듀얼 모멘텀 GEM", "GTAA 5 (파버)",
                                      "올웨더 (달리오)", "원조 LAA (실업률 제외)"]}
ALTERNATIVES["영구 포트폴리오"] = BENCH["영구 포트폴리오"]
ALTERNATIVES["60/40 (S&P·10년채)"] = S.hold({"SPX": .6, "UST10": .4})


def run_plan(plan: dict, m, start: str) -> dict:
    return {k: run(fn, m, start, END) for k, fn in plan.items()}


def rolling_compare(a: dict, b: dict, w: dict, months: int = 36) -> dict:
    ra = pd.DataFrame({k: v["ret"] for k, v in a.items()})
    rb = pd.DataFrame({k: v["ret"] for k, v in b.items()})
    ws = pd.Series(w) / sum(w.values())
    win_r = win_dd = n = 0
    for i in range(len(ra) - months + 1):
        va = ((1 + ra.iloc[i:i + months]).cumprod() * ws).sum(axis=1)
        vb = ((1 + rb.iloc[i:i + months]).cumprod() * ws).sum(axis=1)
        win_r += va.iloc[-1] > vb.iloc[-1]
        win_dd += (va / va.cummax()).min() >= (vb / vb.cummax()).min()
        n += 1
    return {"수익 앞선 비율": win_r / n, "하락 작거나 같은 비율": win_dd / n, "구간 수": n}


def main(path: str) -> None:
    cfg = json.loads(open(path, encoding="utf-8").read())
    w = cfg["accounts"]
    m = prepare(krw=True)
    cash_r = m.ret()[CASH]
    cols = ["CAGR", "변동성", "MDD", "샤프", "MAR", "최악의 해", "최장 회복(개월)"]
    P = plans(cfg)
    res = {name: run_plan(p, m, START) for name, p in P.items()}
    port = {name: combine(r, w)[0] for name, r in res.items()}

    # 1. 현재 포트폴리오 정리: 규칙이 마지막으로 정한 비중(2026-09 말 판정) × 계좌 금액
    total = sum(w.values())
    rows = []
    for acct, r in res["① 지금 그대로"].items():
        last = r["weights"].iloc[-1]
        for asset, x in last.items():
            rows.append({"계좌": acct, "분류": CATEGORY.get(asset, asset), "자산": asset, "비중": w[acct] * x / total})
    snap = pd.DataFrame(rows)
    print("## 1. 지금 포트폴리오 (2026-09 말 규칙 판정 기준 추정)\n")
    print((snap.groupby("분류")["비중"].sum().sort_values(ascending=False) * 100).round(1).to_markdown())
    print()
    print((snap.pivot_table(index="계좌", columns="분류", values="비중", aggfunc="sum").fillna(0) * 100).round(1).to_markdown())

    # 2. 전체 계좌 비교
    alt = {}
    invest = {k: v for k, v in w.items() if k != "CASH"}
    for name, fn in ALTERNATIVES.items():
        r = run(fn, m, START, END)
        alt[f"(대안) 별도 현금 빼고 전부 {name}"] = combine({"ALL": r, "CASH": res["① 지금 그대로"]["CASH"]},
                                                     {"ALL": sum(invest.values()), "CASH": w["CASH"]})[0]
    table = {**port, **alt}
    print(f"\n## 2. 전체 계좌 백테스트 ({START[:7]}~{END[:7]}, 원화)\n")
    print(fmt(pd.DataFrame({k: stats(v, cash_r) for k, v in table.items()}).T[cols]).to_markdown())
    print()
    print(fmt(crisis(table)).drop(columns=["닷컴 2000-03~2002-09"]).to_markdown())

    # 3. 듀얼 모멘텀 검증
    print("\n## 3. 일반계좌 1 듀얼 모멘텀 검증\n")
    periods = [("2007-03-31", "2012-12-31"), ("2012-12-31", "2019-12-31"), ("2019-12-31", END)]
    sub = {}
    for name in ["① 지금 그대로", "② 일반계좌1 = 국내·미국 듀얼 모멘텀", "④ 일반계좌1 = 국내 주식 절반 필터"]:
        row = {}
        for a, b in periods:
            r = {k: v.loc[(v.index > a) & (v.index <= b)] for k, v in res[name].items()}
            s = stats(combine(r, w)[0], cash_r)
            row[f"{a[:4]}~{b[:4]} 연수익"] = s["CAGR"]
            row[f"{a[:4]}~{b[:4]} MDD"] = s["MDD"]
        sub[name] = row
    t = pd.DataFrame(sub).T.map(lambda v: f"{v * 100:.1f}%")
    print("### 기간을 나눠 보기 (전체 계좌)\n")
    print(t.to_markdown())
    print("\n### 판단 기간(룩백)을 바꿔 보기 (전체 계좌)\n")
    sens = {}
    for label, fn in {"6개월": S.relative_momentum(("KOSPI", "SPX"), months=6),
                      "9개월": S.relative_momentum(("KOSPI", "SPX"), months=9),
                      "12개월 (추천)": S.relative_momentum(("KOSPI", "SPX")),
                      "13612W 가중": S.relative_momentum(("KOSPI", "SPX"), score="13612w")}.items():
        r = {**res["① 지금 그대로"], "EM": run(fn, m, START, END)}
        sens[label] = stats(combine(r, w)[0], cash_r)
    sens["(비교) 지금 그대로"] = stats(port["① 지금 그대로"], cash_r)
    print(fmt(pd.DataFrame(sens).T[["CAGR", "MDD", "샤프", "최악의 해"]]).to_markdown())
    print("\n### 3년씩 잘라서 비교 (② vs ①, 매달 시작)\n")
    for mine, other in [("② 일반계좌1 = 국내·미국 듀얼 모멘텀", "① 지금 그대로"),
                        ("② 일반계좌1 = 국내·미국 듀얼 모멘텀", "④ 일반계좌1 = 국내 주식 절반 필터"),
                        ("⑤ 일반계좌1 그대로 + SSO·ISA 제안 규칙", "① 지금 그대로")]:
        rc = rolling_compare(res[mine], res[other], w)
        print(f"- {mine[:1]}가 {other}보다 3년 수익이 앞선 구간 {rc['수익 앞선 비율'] * 100:.0f}%, "
              f"최대 하락이 작거나 같은 구간 {rc['하락 작거나 같은 비율'] * 100:.0f}% (구간 {rc['구간 수']}개)")
    held = res["② 일반계좌1 = 국내·미국 듀얼 모멘텀"]["EM"]["weights"].map(lambda x: max(x, key=x.get))
    share = held.value_counts(normalize=True)
    print(f"- 일반계좌 1이 머문 시간: " + ", ".join(f"{k} {v * 100:.0f}%" for k, v in share.items())
          + f" · 연 평균 전환 {(held != held.shift()).sum() / (len(held) / 12):.1f}회 · 마지막 판정 {held.iloc[-1]}")


if __name__ == "__main__":
    main(*sys.argv[1:])
