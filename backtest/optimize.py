"""계좌별 거래 가능 시장을 지키면서 전략 조합을 넓게 비교한다: python -m backtest.optimize 구성.json

구성.json (저장소에 올리지 않는다):
  {"accounts": {"PEN_FREE": 금액, "PEN_TAX": 금액, "ISA": 금액, "GEN1": 금액, "GEN2": 금액, "GOLD": 금액, "CASH": 금액},
   "em_stocks": {"SAMSUNG": 비율, ...}, "em_cash_share": 0.15}

계좌별 규칙
- 연금저축(PEN_FREE·PEN_TAX): 국내 상장 ETF만, 레버리지 불가. 세금은 인출 때까지 미뤄지므로 0으로 본다.
- ISA: 국내 상장 ETF(레버리지 가능). 비과세 한도 안이라고 보고 0.
- 일반계좌(GEN1·GEN2): 국내 주식 + 미국 상장 ETF. 국내 주식 매매 차익 0%,
  미국 상장 ETF 이익 22%(실현 비율은 연 회전율로 근사), 현금 이자 15.4%.
- 금 계좌: KRX 금현물 보유(비과세). 별도 현금: 현금(투자 판단 밖).
계좌 사이에는 돈을 옮기지 않는다(시작 금액으로 출발해 각자 불어남).

과최적화를 피하려고 앞 절반(2007-03~2016-12)과 뒤 절반(2017-01~2026-09)에서 모두 괜찮은 조합만 고른다.
"""
from __future__ import annotations

import itertools
import json
import sys

import numpy as np
import pandas as pd

from backtest import strategies as S
from backtest.engine import CASH, run
from backtest.run import END, prepare

START = "2007-03-31"
SPLIT = "2016-12-31"
KR_EQUITY = {"KOSPI", "SAMSUNG", "HYNIX", "HYUNDAI", "IBK", "TOP10"}


def laa_original_kr(d, ctx):
    m = ctx.m
    sw = "NDX" if ctx.val(m.close, "SPX") > ctx.val(m.sma(10), "SPX") else CASH
    return {"SPX": .25, "GOLD": .25, "UST10": .25, sw: .25}


def pension_menu() -> dict:
    """국내 상장 ETF로 살 수 있는 자산만 쓴다(신호용 TIP·AGG는 매매하지 않음)."""
    off = ("SPX", "NDX", "EFA", "EEM", "GOLD", "UST10", "TLT")
    return {
        "GSM(현재)": S.gsm(),
        "GSM+금·채권 상위2": S.gsm(cands=("NDX", "SPX", "WORLD", "EURO", "GOLD", "UST10"), top=2),
        "LAA 변형(현재)": S.laa_variant(),
        "6자산 고정": S.hold(S.LAA_TARGET, S.QUARTER_MONTHS),
        "원조 LAA": laa_original_kr,
        "HAA(국내 ETF판)": S.haa(offense=off, top=4),
        "BAA(국내 ETF판)": S.baa(offense=off, defense=("UST10", "TLT", "GOLD", CASH), top_off=3, top_def=3),
        "DAA(국내 ETF판)": S.daa(offense=off, defense=("UST10", CASH), top=3),
        "영구 포트폴리오": S.hold({"SPX": .25, "TLT": .25, "GOLD": .25, CASH: .25}, (12,)),
        "60/40": S.hold({"SPX": .6, "UST10": .4}, (12,)),
        "올웨더(간이)": S.hold({"SPX": .3, "TLT": .4, "UST10": .15, "GOLD": .15}, (12,)),
        "GTAA(국내 ETF판)": S.gtaa(assets=("SPX", "EFA", "EEM", "UST10", "GOLD")),
        "S&P500 보유": S.hold({"SPX": 1}),
    }


def isa_menu() -> dict:
    return {
        **pension_menu(),
        "나스닥2배 단계(현재)": S.ladder("QLD", "NDX_USD", 0.0, S.ISA_STEPS),
        "나스닥2배 단계+SMA 현금": S.ladder("QLD", "NDX_USD", 0.0, S.ISA_STEPS, sma_sell=True),
        "나스닥2배 SMA 추세": S.gsm(cands=("QLD",), invest=1.0),
        "S&P2배 SMA 추세": S.gsm(cands=("SSO",), invest=1.0),
        "현금 대기": S.hold({CASH: 1}),
    }


def general_menu(cfg: dict) -> dict:
    return {
        "국내 실제 구성 보유": S.mix(cfg["em_stocks"], 1 - cfg["em_cash_share"]),
        "KODEX200 보유": S.hold({"KOSPI": 1}),
        "KODEX200 절반 필터": S.mix({"KOSPI": 1}, 1.0, "KOSPI", .5),
        "국내·미국 듀얼": S.relative_momentum(("KOSPI", "SPX")),
        "국내 50/S&P 50": S.hold({"KOSPI": .5, "SPX": .5}, (12,)),
        "S&P500 보유": S.hold({"SPX": 1}),
        "SSO 단계(현재)": S.ladder("SSO", "SPX_USD", .70, S.SSO_STEPS),
        "SSO 단계+추가매수 보류": S.ladder("SSO", "SPX_USD", .70, S.SSO_STEPS, sma_exit=True),
        "SSO 70/현금30": S.hold({"SSO": .7, CASH: .3}),
        "6자산 고정(미국 ETF)": S.hold(S.LAA_TARGET, (12,)),
        "영구(미국 ETF)": S.hold({"SPX": .25, "TLT": .25, "GOLD": .25, CASH: .25}, (12,)),
    }


def after_tax(res: pd.DataFrame) -> pd.Series:
    """일반계좌 세후 월수익률(연 단위 근사)."""
    r = res["ret"]
    w = res["weights"]
    us = w.map(lambda x: sum(v for k, v in x.items() if k not in KR_EQUITY and k != CASH))
    cash = w.map(lambda x: x.get(CASH, 0))
    out = r.copy()
    years = r.index.year
    for y in np.unique(years):
        sel = years == y
        g = (1 + r[sel]).prod() - 1
        realize = min(1.0, res["turnover"][sel].sum())
        tax = max(g, 0) * (.22 * us[sel].mean() * realize + .154 * cash[sel].mean())
        out[sel] = (1 + r[sel]) * (1 - tax) ** (1 / sel.sum()) - 1
    return out


def metrics(paths: np.ndarray, idx: pd.DatetimeIndex) -> dict:
    """paths: (조합 수, 개월) 가치. 시작값 1."""
    def seg(p):
        r = p[:, 1:] / p[:, :-1] - 1
        years = r.shape[1] / 12
        cagr = (p[:, -1] / p[:, 0]) ** (1 / years) - 1
        vol = r.std(axis=1) * np.sqrt(12)
        mdd = (p / np.maximum.accumulate(p, axis=1) - 1).min(axis=1)
        return cagr, vol, mdd
    full = np.concatenate([np.ones((paths.shape[0], 1)), paths], axis=1)
    k = int((idx <= pd.Timestamp(SPLIT)).sum())
    c, v, d = seg(full)
    c1, v1, d1 = seg(full[:, :k + 1])
    c2, v2, d2 = seg(full[:, k:])
    yr = pd.Series(idx.year)
    ends = [i for i in range(len(idx)) if i == len(idx) - 1 or yr[i + 1] != yr[i]]
    starts = [0] + [e + 1 for e in ends[:-1]]
    yearly = np.stack([full[:, e + 1] / full[:, s] - 1 for s, e in zip(starts, ends)], axis=1)
    return dict(CAGR=c, 변동성=v, MDD=d, 최악의해=yearly.min(axis=1),
                앞CAGR=c1, 앞MDD=d1, 뒤CAGR=c2, 뒤MDD=d2)


def main(path: str, top: int = 15) -> None:
    cfg = json.loads(open(path, encoding="utf-8").read())
    acc = cfg["accounts"]
    total = sum(acc.values())
    w = {k: v / total for k, v in acc.items()}
    m = prepare(krw=True)

    def paths(menu, taxed=False):
        out = {}
        for name, fn in menu.items():
            res = run(fn, m, START, END)
            r = after_tax(res) if taxed else res["ret"]
            out[name] = (1 + r).cumprod().values
        return out, res.index

    pen, idx = paths(pension_menu())
    isa, _ = paths(isa_menu())
    gen, _ = paths(general_menu(cfg), taxed=True)
    fixed = w["GOLD"] * paths({"g": S.hold({"GOLD": 1})})[0]["g"] + w["CASH"] * paths({"c": S.hold({CASH: 1})})[0]["c"]

    pn, iname, gn = list(pen), list(isa), list(gen)
    P = np.stack([pen[k] for k in pn])
    I = np.stack([isa[k] for k in iname])
    G = np.stack([gen[k] for k in gn])
    pairs = list(itertools.product(range(len(gn)), range(len(gn))))
    G12 = np.stack([w["GEN1"] * G[a] + w["GEN2"] * G[b] for a, b in pairs])
    rows = []
    for a, b, c in itertools.product(range(len(pn)), range(len(pn)), range(len(iname))):
        base = w["PEN_FREE"] * P[a] + w["PEN_TAX"] * P[b] + w["ISA"] * I[c] + fixed
        mt = metrics(base[None, :] + G12, idx)
        for j, (ga, gb) in enumerate(pairs):
            rows.append((a, b, c, ga, gb, *[mt[k][j] for k in mt]))
    cols = ["pf", "pt", "isa", "g1", "g2", "CAGR", "변동성", "MDD", "최악의해", "앞CAGR", "앞MDD", "뒤CAGR", "뒤MDD"]
    df = pd.DataFrame(rows, columns=cols)
    df["연금(비과세)"] = df.pf.map(lambda i: pn[i])
    df["연금(과세)"] = df.pt.map(lambda i: pn[i])
    df["ISA"] = df.isa.map(lambda i: iname[i])
    df["일반1"] = df.g1.map(lambda i: gn[i])
    df["일반2"] = df.g2.map(lambda i: gn[i])
    df["샤프근사"] = df.CAGR / df.변동성
    df["앞MAR"] = df.앞CAGR / -df.앞MDD
    df["뒤MAR"] = df.뒤CAGR / -df.뒤MDD
    df["견고MAR"] = df[["앞MAR", "뒤MAR"]].min(axis=1)
    df.to_pickle(path + ".results.pkl")

    names = ["연금(비과세)", "연금(과세)", "ISA", "일반1", "일반2"]
    show = names + ["CAGR", "MDD", "최악의해", "앞CAGR", "뒤CAGR", "앞MDD", "뒤MDD"]

    def pct(t):
        t = t[show].copy()
        for c in show[5:]:
            t[c] = t[c].map(lambda v: f"{v * 100:.1f}%")
        return t

    cur = df[(df["연금(비과세)"] == "GSM(현재)") & (df["연금(과세)"] == "LAA 변형(현재)") &
             (df.ISA == "나스닥2배 단계(현재)") & (df.일반1 == "국내 실제 구성 보유") & (df.일반2 == "SSO 단계(현재)")]
    print(f"조합 수: {len(df):,}  ({len(pn)}×{len(pn)}×{len(iname)}×{len(gn)}×{len(gn)})\n")
    print("## 지금 조합\n")
    print(pct(cur).to_markdown(index=False))
    c0 = cur.iloc[0]
    better = df[(df.CAGR >= c0.CAGR) & (df.MDD >= c0.MDD)]
    robust = better[(better.앞CAGR >= c0.앞CAGR) & (better.뒤CAGR >= c0.뒤CAGR) &
                    (better.앞MDD >= c0.앞MDD) & (better.뒤MDD >= c0.뒤MDD)]
    print(f"\n지금보다 수익·최대 하락이 모두 나은 조합: 전체 기간 {len(better):,}개, 앞·뒤 절반 모두 나은 조합 {len(robust):,}개\n")
    for title, lo, hi in [("안정형 (최대 하락 -12% 이내)", -.12, 0), ("균형형 (-12% ~ -16%)", -.16, -.12),
                          ("성장형 (-16% ~ -20%)", -.20, -.16)]:
        band = df[(df.MDD > lo) & (df.MDD <= hi) & (df.앞MDD > lo - .03) & (df.뒤MDD > lo - .03)]
        best = band.sort_values("견고MAR", ascending=False).head(top)
        print(f"## {title}: 앞·뒤 절반 중 나쁜 쪽 MAR(연수익÷최대 하락) 상위\n")
        print(pct(best).to_markdown(index=False))
        # 상위 조합에 자주 나온 전략
        freq = {n: band.sort_values("견고MAR", ascending=False).head(200)[n].value_counts().head(3).to_dict() for n in names}
        print("\n상위 200개에 자주 나온 전략:", json.dumps(freq, ensure_ascii=False), "\n")
    # 과최적화 점검: 앞 절반 최고 조합들의 뒤 절반 순위
    df["뒤순위"] = df.뒤MAR.rank(ascending=False, pct=True)
    first_best = df.sort_values("앞MAR", ascending=False).head(100)
    print(f"앞 절반 MAR 상위 100개 조합의 뒤 절반 순위(상위 %): 중간값 {first_best.뒤순위.median() * 100:.0f}%, "
          f"상위 25% 안에 든 비율 {(first_best.뒤순위 <= .25).mean() * 100:.0f}%")
    # 계좌별 전략의 평균 효과(다른 계좌는 전부 섞어서)
    print("\n## 계좌별 전략의 평균 효과 (다른 계좌 조합 전체 평균)\n")
    for n in names:
        g = df.groupby(n)[["CAGR", "MDD", "견고MAR"]].mean().sort_values("견고MAR", ascending=False)
        g["CAGR"] = g.CAGR.map(lambda v: f"{v * 100:.2f}%")
        g["MDD"] = g.MDD.map(lambda v: f"{v * 100:.1f}%")
        g["견고MAR"] = g.견고MAR.map(lambda v: f"{v:.2f}")
        print(f"### {n}\n")
        print(g.to_markdown())
        print()


if __name__ == "__main__":
    main(*sys.argv[1:])
