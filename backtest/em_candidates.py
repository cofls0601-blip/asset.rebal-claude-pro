"""일반계좌 1(EM, 국내 주식) 전략 후보 비교: python -m backtest.em_candidates 비중.json

원화 기준. 단독 성적과, 다른 계좌는 현재 규칙으로 둔 전체 자산 성적을 함께 본다.
비중.json은 backtest.portfolio와 같은 형식이며 저장소에 올리지 않는다.
"""
import json, sys, pandas as pd
from backtest import strategies as S
from backtest.engine import CASH, run, stats
from backtest.portfolio import SLEEVES, FIXED, combine
from backtest.run import prepare, END, fmt, crisis

def half_filter(d, ctx):
    m = ctx.m
    on = ctx.val(m.close, "KOSPI") > ctx.val(m.sma(10), "KOSPI")
    return {"KOSPI": 1.0} if on else {"KOSPI": .5, CASH: .5}

def kr_dual(d, ctx):  # 국내 주식 vs 국고채10년 vs 현금, 12개월 수익 1위
    mo = ctx.m.mom_total(12)
    best = max(("KOSPI", "KTB10"), key=lambda a: ctx.val(mo, a))
    return {best: 1.0} if ctx.val(mo, best) > ctx.val(mo, CASH) else {CASH: 1.0}

def kr_balanced_filter(d, ctx):  # 주식 60 (SMA 아래면 현금) / 국고채10년 40
    m = ctx.m
    eq = "KOSPI" if ctx.val(m.close, "KOSPI") > ctx.val(m.sma(10), "KOSPI") else CASH
    return {eq: .6, "KTB10": .4}

CANDS_LONG = {
    "① 지금: 국내 주식 보유": S.hold({"KOSPI": 1}),
    "② 국내 주식 + SMA 필터(아래면 현금)": S.gsm(cands=("KOSPI",), invest=1.0),
    "③ 절반만 필터(아래면 주식 50%)": half_filter,
}
CANDS_SHORT = {
    **CANDS_LONG,
    "④ 국내 주식 60 / 국고채10년 40": S.hold({"KOSPI": .6, "KTB10": .4}),
    "⑤ ④ + 주식 몫 SMA 필터": kr_balanced_filter,
    "⑥ 국내 듀얼모멘텀(주식·국고채·현금)": kr_dual,
}


def main(path):
    w = json.load(open(path))
    m = prepare(krw=True)
    cash_r = m.ret()[CASH]
    cols = ["CAGR", "변동성", "MDD", "샤프", "최악의 해", "연 회전율"]
    for start, cands in (("2005-01-31", CANDS_LONG), ("2012-11-30", CANDS_SHORT)):
        base = {k: run(fn, m, start, END) for k, fn in {**SLEEVES["현재"], **FIXED}.items()}
        rows, tot, cr = {}, {}, {}
        for name, fn in cands.items():
            r = run(fn, m, start, END)
            rows[name] = stats(r, cash_r); cr[name] = r
            port, _ = combine({**base, "EM": r}, w)
            tot[name] = stats(port, cash_r); cr["전체: " + name] = port
        print(f"\n### {start[:7]}~ 일반계좌 1 단독")
        print(fmt(pd.DataFrame(rows).T[cols]).to_markdown())
        print(f"\n### {start[:7]}~ 전체 자산(다른 계좌는 현재 규칙)")
        print(fmt(pd.DataFrame(tot).T[["CAGR", "변동성", "MDD", "샤프", "최악의 해"]]).to_markdown())
        print(fmt(crisis(cr)).to_markdown())

if __name__ == "__main__":
    main(sys.argv[1])
