"""일반계좌 1을 실제 구성(종목 비율 + 계좌 현금)으로 백테스트: python -m backtest.em_mix 구성.json

구성.json 예: {"stocks": {"SAMSUNG": 30, "KOSPI": 70}, "stock_amt": 100, "cash_amt": 20,
            "others": {"GSM": 10, "LAA": 20, "GOLD": 10, "ISA": 5, "SSO": 15, "CASH": 15}}
종목 이름: SAMSUNG, HYNIX, HYUNDAI, IBK, KOSPI(KODEX 200), TOP10(TIGER 코리아TOP10).
실제 비율·금액이 담긴 파일은 저장소에 올리지 않는다.
"""
import json, sys, pandas as pd
from backtest import strategies as S
from backtest.engine import CASH, run, stats
from backtest.portfolio import SLEEVES, FIXED, combine
from backtest.run import prepare, END, fmt, crisis

cfg = json.load(open(sys.argv[1]))
mix = {k: v / sum(cfg["stocks"].values()) for k, v in cfg["stocks"].items()}
st = cfg["stock_amt"] / (cfg["stock_amt"] + cfg["cash_amt"])

def account(stock_share_when_below, months=(12,)):
    """주식 몫은 구성 비중 유지(연 1회 복원), KODEX 200이 SMA 아래면 주식 몫을 줄임."""
    def strat(d, ctx):
        m = ctx.m
        below = ctx.val(m.close, "KOSPI") < ctx.val(m.sma(10), "KOSPI")
        s = st * stock_share_when_below if below else st
        prev_below = ctx.state.get("below")
        ctx.state["below"] = below
        first = not ctx.state.get("started"); ctx.state["started"] = True
        if first or d.month in months or below != prev_below:
            w = {k: s * v for k, v in mix.items()}; w[CASH] = 1 - s
            return w
        return None
    return strat

m = prepare(krw=True)
cash_r = m.ret()[CASH]
first = max(m.total[k].first_valid_index() for k in mix)
cands = {
    "① 지금 구성 그대로 (현금 15% 유지)": account(1.0),
    "② SMA 아래면 주식 전부 현금": account(0.0),
    "③ 절반 필터 (SMA 아래면 주식 절반)": account(0.5),
    "(비교) KODEX 200 100%": S.hold({"KOSPI": 1}),
}
cols = ["CAGR", "변동성", "MDD", "샤프", "최악의 해", "연 회전율"]
weights = {**cfg["others"], "EM": cfg["stock_amt"] + cfg["cash_amt"]}
print("first data", first.date(), weights)
for start in ("2005-01-31", "2012-11-30"):
    base = {k: run(fn, m, start, END) for k, fn in {**SLEEVES["현재"], **FIXED}.items()}
    rows, tot, cr = {}, {}, {}
    for name, fn in cands.items():
        r = run(fn, m, start, END); rows[name] = stats(r, cash_r); cr[name] = r
        port, _ = combine({**base, "EM": r}, weights); tot[name] = stats(port, cash_r); cr["전체: " + name] = port
    print(f"\n### {start[:7]}~ 일반계좌 1 단독"); print(fmt(pd.DataFrame(rows).T[cols]).to_markdown())
    print(f"\n### 전체 자산"); print(fmt(pd.DataFrame(tot).T[cols[:5]]).to_markdown())
    print(fmt(crisis(cr)).to_markdown())
# 종목별 성적과 최근 상태
print()
for k in [*mix, "KOSPI"]:
    c = m.close[k].dropna(); t = m.total[k].dropna()
    r = t.pct_change().loc["2012-12":]
    dd = (t / t.cummax() - 1).min()
    print(f"{k:8s} 2013~ 연{((1+r).prod()**(12/len(r))-1)*100:5.1f}% 변동성{r.std()*12**.5*100:5.1f}% 최대하락{dd*100:6.1f}%(2000~) | 2025-12→2026-06 {(c['2026-06'].iloc[-1]/c['2025-12'].iloc[-1]-1)*100:+.0f}% | 2026-06→09 {(c['2026-09'].iloc[-1]/c['2026-06'].iloc[-1]-1)*100:+.0f}%")
R = m.total[list(mix)].pct_change().loc["2015":]
print("\n상관계수(월, 2015~)\n", R.corr().round(2).to_string())
