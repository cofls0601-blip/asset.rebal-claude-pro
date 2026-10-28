"""일반계좌 1 운영 전략 후보를 전체 자산 기준으로 비교: python -m backtest.em_options 구성.json

구성.json은 backtest.em_mix와 같은 형식(others와 계좌 금액만 쓴다). 저장소에 올리지 않는다.
세후 수익은 연 단위 근사: 국내 주식 0%, 그 밖의 자산 이익에 15.4%.
"""
import json, sys, numpy as np, pandas as pd
from backtest import strategies as S
from backtest.engine import CASH, run, stats
from backtest.portfolio import SLEEVES, FIXED, combine
from backtest.run import prepare, END, fmt, crisis

cfg = json.load(open(sys.argv[1]))
weights = {**cfg["others"], "EM": cfg["stock_amt"] + cfg["cash_amt"]}
m = prepare(krw=True)
cash_r = m.ret()[CASH]

def above(ctx, a): return ctx.val(m.close, a) > ctx.val(m.sma(10), a)

def filt(eq, keep_below, safe=CASH):
    def f(d, ctx):
        s = 1.0 if above(ctx, eq) else keep_below
        return {eq: s, safe: 1 - s}
    return f

def kr_dual(d, ctx):
    mo = ctx.m.mom_total(12)
    best = max(("KOSPI", "KTB10"), key=lambda a: ctx.val(mo, a))
    return {best: 1.0} if ctx.val(mo, best) > ctx.val(mo, CASH) else {CASH: 1.0}

def mix_filter(eq_w, bond="KTB10"):
    def f(d, ctx):
        e = eq_w if above(ctx, "KOSPI") else eq_w / 2
        return {"KOSPI": e, bond: eq_w - e + (1 - eq_w)} if False else {"KOSPI": e, CASH: eq_w - e, bond: 1 - eq_w}
    return f

def kr_us_dual(d, ctx):  # 국내 주식 vs S&P500(원화) vs 현금
    mo = ctx.m.mom_total(12)
    best = max(("KOSPI", "SPX"), key=lambda a: ctx.val(mo, a))
    return {best: 1.0} if ctx.val(mo, best) > ctx.val(mo, CASH) else {CASH: 1.0}

# 세금 구분: 국내 주식 0%, 그 밖(국내 상장 해외·채권 ETF, 단기채)은 이익의 15.4%
TAXED = {"SPX", "NDX", "GOLD", "UST10", "KTB10", "KTB3", CASH, "EEM", "EFA"}

C = {
    "a. 국내 주식 보유": S.hold({"KOSPI": 1}),
    "b. 국내 주식 절반 필터 (현금)": filt("KOSPI", .5),
    "c. 국내 주식 SMA 필터 (현금)": filt("KOSPI", 0),
    "d. 절반 필터, 필터 몫은 국고채10년": filt("KOSPI", .5, "KTB10"),
    "e. 국내 주식 70 / 국고채10년 30 (연 1회)": S.hold({"KOSPI": .7, "KTB10": .3}, (12,)),
    "f. e + 주식 몫 절반 필터": mix_filter(.7),
    "g. 국내 듀얼(주식·국고채·현금)": kr_dual,
    "h. 국내 주식 vs S&P500 듀얼": kr_us_dual,
    "i. 국내 주식 50 / 신흥국 30 / 국고채 20": S.hold({"KOSPI": .5, "EEM": .3, "KTB10": .2}, (12,)),
}

def after_tax(res):
    """연 단위 근사: 과세 자산 몫의 그해 이익에 15.4%(국내 주식은 0%). 매매가 적은 보유형도 매년 실현한다고 봐서 보수적."""
    r = res["ret"].copy()
    taxed_share = res["weights"].map(lambda w: sum(v for k, v in w.items() if k in TAXED))
    yr = r.index.year
    out = r.copy()
    for y in np.unique(yr):
        sel = yr == y
        g = (1 + r[sel]).prod() - 1
        tax = max(g, 0) * .154 * taxed_share[sel].mean()
        out[sel] = (1 + r[sel]) * (1 - tax) ** (1 / sel.sum()) - 1
    return pd.DataFrame({"ret": out, "turnover": res["turnover"]})

start = "2012-11-30"
base = {k: run(fn, m, start, END) for k, fn in {**SLEEVES["현재"], **FIXED}.items()}
rest = combine(base, {k: v for k, v in weights.items() if k != "EM"})[0]["ret"]
rows, tot, cr = {}, {}, {}
for name, fn in C.items():
    r = run(fn, m, start, END); rt = after_tax(r)
    s = stats(r, cash_r); st = stats(rt, cash_r)
    port, _ = combine({**base, "EM": rt}, weights); sp = stats(port, cash_r)
    rows[name] = {"연수익": s["CAGR"], "세후(근사)": st["CAGR"], "MDD": s["MDD"], "연 회전율": s["연 회전율"],
                  "다른 계좌와 상관": r["ret"].corr(rest)}
    tot[name] = {"CAGR": sp["CAGR"], "변동성": sp["변동성"], "MDD": sp["MDD"], "샤프": sp["샤프"], "최악의 해": sp["최악의 해"]}
    cr[name] = port
f = lambda v: f"{v*100:.1f}%"
t = pd.DataFrame(rows).T
for c in ["연수익", "세후(근사)", "MDD", "연 회전율"]: t[c] = t[c].map(f)
t["다른 계좌와 상관"] = t["다른 계좌와 상관"].map(lambda v: f"{v:.2f}")
print(f"### {start[:7]}~ 일반계좌 1 단독\n", t.to_markdown())
print("\n### 전체 자산 (일반계좌 1은 세후 근사, 다른 계좌는 현재 규칙)\n", fmt(pd.DataFrame(tot).T).to_markdown())
print(fmt(crisis(cr)).drop(columns=["닷컴 2000-03~2002-09", "금융위기 2007-11~2009-02"]).to_markdown())
# 장기(국고채 없는 후보만)
start = "2005-01-31"
base = {k: run(fn, m, start, END) for k, fn in {**SLEEVES["현재"], **FIXED}.items()}
tot = {}
for name in ["a. 국내 주식 보유", "b. 국내 주식 절반 필터 (현금)", "c. 국내 주식 SMA 필터 (현금)", "h. 국내 주식 vs S&P500 듀얼"]:
    rt = after_tax(run(C[name], m, start, END))
    port, _ = combine({**base, "EM": rt}, weights); sp = stats(port, cash_r)
    tot[name] = {k: sp[k] for k in ["CAGR", "변동성", "MDD", "샤프", "최악의 해"]}
print("\n### 2005~ 전체 자산\n", fmt(pd.DataFrame(tot).T).to_markdown())
