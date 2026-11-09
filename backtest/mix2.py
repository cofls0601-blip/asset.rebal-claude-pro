"""전략 다양성·궁합을 먼저 보는 계좌별 전략 조합 찾기 (DGA·황금나비·가속듀얼 포함).

python -m backtest.mix2 비중.json

비중.json (저장소에 올리지 않는다):
  {"PEN_FREE": 금액, "PEN_TAX": 금액, "ISA": 금액, "GEN1": 금액, "GEN2": 금액, "GOLD": 금액, "CASH": 금액}

- 원화 2005-01~2026-09와 달러 1997-04~2026-09(원화 약세 도움 없는 시험)를 함께 본다.
- 계좌마다 서로 다른 전략을 쓰고(같은 전략 두 번 금지), 같은 종류(교체형·고정형 등)는 두 계좌까지만.
- 궁합: 계좌들(금 계좌 포함, 별도 현금 제외)의 월수익 상관계수를 금액 비중으로 평균낸 값. 낮을수록 서로 보완한다.
- 세금: 일반계좌는 optimize.after_tax 근사(미국 ETF 이익 22%, 실현 비율=회전율).

DGA 근사: S&P500 배당수익률 = SPY 12개월 (총수익 ÷ 가격 수익) − 1. 금리차 = ^TNX − ^IRX.
SCHD 상장(2011-10) 전은 IWD(가치주), 그 전은 S&P500. PDBC 전은 DBC, 2006-03 전은 원자재를 방어 후보에서 뺀다.
TIP(2003-12) 전은 미국 중기국채(VFITX)로 대신한다.
"""
from __future__ import annotations

import itertools
import json
import sys

import numpy as np
import pandas as pd

from backtest import strategies as S
from backtest.best_mix import GSM2, seg_stats, trend
from backtest.engine import CASH, Market, build_market, run
from backtest.optimize import after_tax, laa_original_kr
from backtest.run import END, prepare

LIMIT = -0.20
STARTS = {"krw": "2005-01-31", "usd": "1997-04-30"}
SPLIT = "2015-12-31"


# ------------------------------------------------------------------ 자료

def _extend(m: Market, krw: bool) -> Market:
    d = m.extra
    close, adj = d["close_d"].copy(), d["adj_d"].copy()
    irx = close["^IRX"].dropna()
    cash = (1 + (irx / 100 / 252).reindex(close.index).ffill().fillna(0)).cumprod() * 100
    close["TBILL_USD"], adj["TBILL_USD"] = cash, cash
    assets = {
        "SCHD": ["SCHD", "IWD", "VFINX"], "BIL": ["BIL", "TBILL_USD"], "COMM": ["PDBC", "DBC"],
        "TIPX": ["TIP", "VFITX"], "SMALL": ["IWM", "VFINX"], "SHORTB": ["SHY", "VFITX"],
    }
    if not krw:
        assets.update({"KOSPI": ["EWY", "VEIEX"], "SPX_USD": ["SPY", "VFINX"], "NDX_USD": ["QQQ", "^NDX"]})
    fx = m.extra["krw"] if False else (close["KRW=X"].dropna() if krw else None)
    k = build_market(close, adj, assets, fx=fx)
    me = m.close.index
    out = Market(close=m.close.join(k.close.reindex(me)), total=m.total.join(k.total.reindex(me)),
                 high52=m.high52.join(k.high52.reindex(me)), extra=dict(d))
    # DGA 신호
    spy_c = build_market(close, adj, {"S": ["SPY", "VFINX"]})
    yld = (spy_c.total["S"] / spy_c.total["S"].shift(12)) / (spy_c.close["S"] / spy_c.close["S"].shift(12)) - 1
    spread = (close["^TNX"] - close["^IRX"]).resample("ME").last()
    out.extra["div_yield"] = yld.reindex(me)
    out.extra["spread"] = spread.reindex(me)
    return out


def markets() -> dict:
    return {"krw": _extend(prepare(krw=True), True), "usd": _extend(prepare(krw=False), False)}


# ------------------------------------------------------------------ 새 전략

def dga(offense=("NDX", "SCHD"), defense=("BIL", "TLT", "COMM"), canary="TIPX", yield_min=.016, spread_min=-.5):
    """DGA: 공격 2개 중 (1·3·6·9·12개월 평균 수익) 높은 쪽 100%.
    위험 신호(TIP < 12개월 평균, S&P 배당수익률 < 1.6%, 10년−3개월 금리차 < -0.5%p) 중 하나라도 켜지면
    방어 3개 중 (월말가 ÷ 6개월 평균)이 가장 높은 것 100%, 그것도 평균 아래면 현금."""
    def strat(d, ctx):
        m = ctx.m
        i = ctx.i
        risk = (ctx.val(m.close, canary) < ctx.val(m.sma(12), canary)
                or m.extra["div_yield"].iloc[i] < yield_min
                or m.extra["spread"].iloc[i] < spread_min)
        if not risk:
            s = sum(m.mom_total(k) for k in (1, 3, 6, 9, 12)) / 5
            return {max(offense, key=lambda a: ctx.val(s, a)): 1.0}
        ratio = m.close / m.sma(6)
        ok = [a for a in defense if not np.isnan(ctx.val(ratio, a))]
        best = max(ok, key=lambda a: ctx.val(ratio, a))
        return {best: 1.0} if ctx.val(ratio, best) >= 1 else {CASH: 1.0}
    return strat


def dga_risk_share(m: Market, start: str) -> float:
    idx = m.close.index
    sel = (idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(END))
    tip = m.close["TIPX"] < m.sma(12)["TIPX"]
    risk = tip | (m.extra["div_yield"] < .016) | (m.extra["spread"] < -.5)
    return float(risk[sel].mean())


BUTTERFLY = {"SPX": .2, "SMALL": .2, "TLT": .2, "SHORTB": .2, "GOLD": .2}

# 이름: (전략, 종류)
def pension_menu() -> dict:
    off = ("SPX", "NDX", "EFA", "EEM", "GOLD", "UST10", "TLT")
    return {
        "GSM 상위2+금·채권": (S.gsm(cands=GSM2, top=2), "교체형"),
        "DGA": (dga(), "교체형"),
        "DAA": (S.daa(offense=off, defense=("UST10", CASH), top=3), "교체형"),
        "가속듀얼모멘텀": (S.adm(risk=("SPX", "EFA"), bond="TLT"), "교체형"),
        "LAA 변형": (S.laa_variant(), "고정+필터"),
        "원조 LAA": (laa_original_kr, "고정+필터"),
        "황금나비": (S.hold(BUTTERFLY, (12,)), "고정형"),
        "영구 포트폴리오": (S.hold({"SPX": .25, "TLT": .25, "GOLD": .25, CASH: .25}, (12,)), "고정형"),
        "올웨더(간이)": (S.hold({"SPX": .3, "TLT": .4, "UST10": .15, "GOLD": .15}, (12,)), "고정형"),
        "60/40": (S.hold({"SPX": .6, "UST10": .4}, (12,)), "고정형"),
        "S&P500 보유": (S.hold({"SPX": 1}), "단일 보유"),
        "나스닥 보유": (S.hold({"NDX": 1}), "단일 보유"),
    }


def isa_menu() -> dict:
    return {
        **pension_menu(),
        "나스닥2배 SMA 추세": (trend("QLD", "NDX_USD"), "레버리지"),
        "S&P2배 SMA 추세": (trend("SSO", "SPX_USD"), "레버리지"),
        "나스닥2배 단계": (S.ladder("QLD", "NDX_USD", 0.0, S.ISA_STEPS), "레버리지"),
    }


def general_menu() -> dict:
    return {
        "국내 주식 보유": (S.hold({"KOSPI": 1}), "단일 보유"),
        "국내 주식 절반 필터": (S.mix({"KOSPI": 1}, 1.0, "KOSPI", .5), "고정+필터"),
        "국내·미국 듀얼": (S.relative_momentum(("KOSPI", "SPX")), "교체형"),
        "국내50/S&P50": (S.hold({"KOSPI": .5, "SPX": .5}, (12,)), "고정형"),
        "S&P500 보유": (S.hold({"SPX": 1}), "단일 보유"),
        "나스닥 보유": (S.hold({"NDX": 1}), "단일 보유"),
        "황금나비": (S.hold(BUTTERFLY, (12,)), "고정형"),
        "영구 포트폴리오": (S.hold({"SPX": .25, "TLT": .25, "GOLD": .25, CASH: .25}, (12,)), "고정형"),
        "6자산 고정": (S.hold(S.LAA_TARGET, (12,)), "고정형"),
        "DGA": (dga(), "교체형"),
        "SSO 단계+추가매수 보류": (S.ladder("SSO", "SPX_USD", .70, S.SSO_STEPS, sma_exit=True), "레버리지"),
    }


ACCTS = ["PEN_FREE", "PEN_TAX", "ISA", "GEN1", "GEN2"]
LABEL = {"PEN_FREE": "연금(비과세)", "PEN_TAX": "연금(과세)", "ISA": "ISA", "GEN1": "일반1", "GEN2": "일반2"}


def series(menu: dict, m: Market, start: str, taxed: bool) -> tuple[dict, dict]:
    out, turn = {}, {}
    for name, (fn, _) in menu.items():
        try:
            res = run(fn, m, start, END)
        except (ValueError, KeyError):
            continue
        out[name] = after_tax(res) if taxed else res["ret"]
        turn[name] = res["turnover"].sum() / (len(res) / 12)
    return out, turn


def main(path: str, top: int = 10) -> None:
    acc = json.loads(open(path, encoding="utf-8").read())
    tot = sum(acc.values())
    w = {k: v / tot for k, v in acc.items()}
    M = markets()
    menus = {"pen": pension_menu(), "isa": isa_menu(), "gen": general_menu()}
    kinds = {n: k for mn in menus.values() for n, (_, k) in mn.items()}
    R, T = {}, {}
    for key, m in M.items():
        R[key], T[key] = {}, {}
        for g, mn in menus.items():
            R[key][g], T[key][g] = series(mn, m, STARTS[key], taxed=(g == "gen"))
        g0 = run(S.hold({"GOLD": 1}), m, STARTS[key], END)["ret"]
        c0 = run(S.hold({CASH: 1}), m, STARTS[key], END)["ret"]
        R[key]["fixed"] = {"GOLD": g0, "CASH": c0}

    # DGA 단독 성적
    print("## DGA 단독\n")
    from backtest.engine import stats
    rows = {}
    for key, m in M.items():
        for st in ([STARTS[key], "2006-09-30"] if key == "usd" else [STARTS[key]]):
            r = run(dga(), m, st, END)
            s = stats(r, m.ret()[CASH])
            s["위험회피 비율"] = dga_risk_share(m, st)
            rows[f"{'원화' if key == 'krw' else '달러'} {st[:7]}~"] = s
    t = pd.DataFrame(rows).T[["CAGR", "변동성", "MDD", "최악의 해", "연 회전율", "위험회피 비율"]]
    print(t.map(lambda v: f"{v * 100:.1f}%").to_markdown())

    names = {g: [n for n in R["krw"][g] if n in R["usd"][g]] for g in ("pen", "isa", "gen")}
    print("\n뺀 전략:", {g: sorted(set(R["krw"][g]) ^ set(R["usd"][g])) for g in names})

    # 상관(원화)
    allr = {}
    for g in ("pen", "isa", "gen"):
        for n in names[g]:
            allr[(g, n)] = R["krw"][g][n]
    allr[("fixed", "GOLD")] = R["krw"]["fixed"]["GOLD"]
    keys = list(allr)
    C = pd.DataFrame({i: allr[k] for i, k in enumerate(keys)}).corr().values
    pos = {k: i for i, k in enumerate(keys)}

    combos = []
    for pf, pt in itertools.permutations(names["pen"], 2):
        for isa in names["isa"]:
            if isa in (pf, pt):
                continue
            for g1, g2 in itertools.permutations(names["gen"], 2):
                if len({pf, pt, isa, g1, g2}) < 5:
                    continue
                ks = [kinds[x] for x in (pf, pt, isa, g1, g2)]
                if max(ks.count(k) for k in set(ks)) > 2:
                    continue
                combos.append((pf, pt, isa, g1, g2))
    print(f"\n조합 수(서로 다른 전략, 같은 종류 2개까지): {len(combos):,}")

    def evaluate(key):
        idx = R[key]["fixed"]["GOLD"].index
        V = {g: {n: (1 + R[key][g][n].reindex(idx)).cumprod().values for n in names[g]} for g in names}
        fixed = w["GOLD"] * (1 + R[key]["fixed"]["GOLD"]).cumprod().values + \
            w["CASH"] * (1 + R[key]["fixed"]["CASH"]).cumprod().values
        out = np.empty((len(combos), len(idx)))
        for i, (pf, pt, isa, g1, g2) in enumerate(combos):
            out[i] = (w["PEN_FREE"] * V["pen"][pf] + w["PEN_TAX"] * V["pen"][pt] + w["ISA"] * V["isa"][isa]
                      + w["GEN1"] * V["gen"][g1] + w["GEN2"] * V["gen"][g2] + fixed)
        val = np.concatenate([np.ones((len(out), 1)), out], axis=1)
        return val[:, 1:] / val[:, :-1] - 1, idx

    rk, idx = evaluate("krw")
    ru, _ = evaluate("usd")
    k = int((idx <= pd.Timestamp(SPLIT)).sum())
    df = pd.DataFrame(combos, columns=ACCTS)
    df["원화 연수익"], df["원화 MDD"], df["원화 최악12개월"] = seg_stats(rk)
    df["앞 연수익"], df["앞 MDD"], _ = seg_stats(rk[:, :k])
    df["뒤 연수익"], df["뒤 MDD"], _ = seg_stats(rk[:, k:])
    df["달러 연수익"], df["달러 MDD"], _ = seg_stats(ru)
    # 궁합: 금액 가중 평균 상관
    wt = [w["PEN_FREE"], w["PEN_TAX"], w["ISA"], w["GEN1"], w["GEN2"], w["GOLD"]]
    corr = []
    for c in combos:
        ids = [pos[("pen", c[0])], pos[("pen", c[1])], pos[("isa", c[2])], pos[("gen", c[3])],
               pos[("gen", c[4])], pos[("fixed", "GOLD")]]
        num = den = 0.0
        for a, b in itertools.combinations(range(6), 2):
            num += wt[a] * wt[b] * C[ids[a], ids[b]]
            den += wt[a] * wt[b]
        corr.append(num / den)
    df["평균 상관"] = corr
    df["견고수익"] = df[["앞 연수익", "뒤 연수익", "달러 연수익"]].min(axis=1)
    df["종류 수"] = df[ACCTS].apply(lambda r: len({kinds[x] for x in r}), axis=1)
    df.to_pickle(path + ".mix2.pkl")
    pd.to_pickle({"names": names, "kinds": kinds, "turn": T["krw"]}, path + ".mix2.meta.pkl")

    ok = df[(df["원화 MDD"] >= LIMIT) & (df["앞 MDD"] >= LIMIT) & (df["뒤 MDD"] >= LIMIT) & (df["달러 MDD"] >= -.30)]
    print(f"원화 -20%(앞·뒤 모두)와 달러 -30% 통과: {len(ok):,}개")
    good = ok[ok["견고수익"] >= ok["견고수익"].quantile(.5)]
    print(f"그중 견고수익 상위 절반: {len(good):,}개 → 평균 상관 낮은 순\n")
    show = good.sort_values(["평균 상관", "견고수익"], ascending=[True, False]).head(top)
    print(fmt(show).to_markdown(index=False))


def fmt(t: pd.DataFrame) -> pd.DataFrame:
    t = t.rename(columns=LABEL).copy()
    for c in ["원화 연수익", "원화 MDD", "원화 최악12개월", "앞 연수익", "앞 MDD", "뒤 연수익", "뒤 MDD", "달러 연수익",
              "달러 MDD", "견고수익"]:
        if c in t:
            t[c] = t[c].map(lambda v: f"{v * 100:.1f}%")
    if "평균 상관" in t:
        t["평균 상관"] = t["평균 상관"].map(lambda v: f"{v:.2f}")
    return t


if __name__ == "__main__":
    main(*sys.argv[1:])
