"""포트폴리오 평가 기준(docs/포트폴리오 평가 기준.md)으로 계좌별 전략 조합에 점수를 매긴다.

python -m backtest.evaluate 비중.json

비중.json (저장소에 올리지 않는다):
  {"PEN_FREE": 금액, "PEN_TAX": 금액, "ISA": 금액, "GEN1": 금액, "GEN2": 금액, "GOLD": 금액, "CASH": 금액}

- 연금·ISA(국내 상품만 거래)는 실제 국내 ETF 시세로 계산하고, 상장 전은 같은 지수의 미국 ETF로 잇는다
  (환노출 = 달러 가격 × 원/달러, 환헤지(H) = 달러 수익률 그대로). 호환 ETF가 없는 자산을 쓰는 전략은 G6 탈락.
- 일반계좌는 미국 상장 ETF·국내 주식(원화 환산, 세금 근사).
- 방패 시험(달러 1997~)은 모든 계좌를 미국 자료로 계산한다(원화 약세 도움 없음).
"""
from __future__ import annotations

import itertools
import json
import sys

import numpy as np
import pandas as pd

from backtest import strategies as S
from backtest.best_mix import seg_stats
from backtest.engine import CASH, Market, build_market, run
from backtest.mix2 import BUTTERFLY, _extend
from backtest.optimize import after_tax, laa_original_kr
from backtest.run import END, prepare

STARTS = {"krw": "2005-01-31", "usd": "1997-04-30"}
SPLIT = "2015-12-31"
GSM2 = ("NDX", "SPX", "WORLD", "EURO", "GOLD", "UST10")

# 자산 → (국내 ETF 코드, 이름, 헤지 여부, 근사 여부, 상장 전 대용 미국 열들)
# 근사: 같은 자산군의 다른 지수. None: 호환 국내 ETF 없음.
DOMESTIC = {
    "NDX": ("133690.KS", "TIGER 미국나스닥100", False, False, ["QQQ", "^NDX"]),
    "SPX": ("360750.KS", "TIGER 미국S&P500", False, False, ["SPY", "VFINX"]),
    "WORLD": ("251350.KS", "KODEX MSCI선진국", False, False, ["URTH", "ACWI", "MIX_WORLD"]),
    "EURO": ("245350.KS", "TIGER 유로스탁스배당30", False, False, ["FDD", "FEZ", "EZU", "VEURX"]),
    "EFA": ("195970.KS", "ARIRANG 선진국MSCI(합성 H)", True, False, ["EFA", "MIX_EAFE"]),
    "EEM": ("195980.KS", "ARIRANG 신흥국MSCI(합성 H)", True, False, ["EEM", "VEIEX"]),
    "GOLD": ("411060.KS", "ACE KRX금현물", False, False, ["GLD", "GC=F", "GOLD_M"]),
    "UST10": ("308620.KS", "KODEX 미국10년국채선물", False, False, ["IEF", "VFITX"]),
    "TLT": ("476760.KS", "ACE 미국30년국채액티브", False, False, ["TLT", "VUSTX"]),
    "SCHD": ("458730.KS", "TIGER 미국배당다우존스", False, False, ["SCHD", "IWD", "VFINX"]),
    "BIL": ("329750.KS", "TIGER 미국달러단기채권액티브", False, False, ["BIL", "TBILL_USD"]),
    "COMM": None,
    "SMALL": ("280930.KS", "KODEX 미국러셀2000(H)", True, False, ["IWM", "VFINX"]),
    "SHORTB": ("329750.KS", "TIGER 미국달러단기채권액티브", False, True, ["SHY", "VFITX"]),
    "QLD": ("418660.KS", "TIGER 미국나스닥100레버리지(합성)", False, False, None),
    "SSO": ("225040.KS", "TIGER 미국S&P500레버리지(합성 H)", True, False, None),
}


def domestic_market(base: Market, usd: Market, available: set) -> tuple[Market, dict]:
    """연금·ISA용 원화 시장. 국내 ETF가 있는 자산만 만든다."""
    close, adj = base.extra["close_d"].copy(), base.extra["adj_d"].copy()
    fx = close["KRW=X"].reindex(close.index).ffill(limit=5)
    cash = (1 + (close["^IRX"] / 100 / 252).reindex(close.index).ffill().fillna(0)).cumprod() * 100
    close["TBILL_USD"], adj["TBILL_USD"] = cash, cash
    assets, info, gaps = {}, {}, {}
    for name, spec in DOMESTIC.items():
        if spec is None or spec[0] not in available:
            info[name] = None
            continue
        code, label, hedged, approx, proxies = spec
        cols = [code]
        if proxies is None:  # 레버리지: 합성 2배 지수(base에 있는 달러/원화 값) 사용
            lev = usd.total[name] if hedged else base.total[name]
            close[f"{name}_PX"] = lev.reindex(close.index).ffill()
            adj[f"{name}_PX"] = close[f"{name}_PX"]
            cols.append(f"{name}_PX")
        else:
            first = [p for p in proxies if p in close]
            ref = adj[first[0]] if hedged else adj[first[0]] * fx
            gap = _gap(adj[code], ref)
            drag = (1 - gap) ** (1 / 252) if gap > 0 else 1.0
            for p in first:
                k = f"{p}_{'H' if hedged else 'K'}"
                base_c = close[p] if hedged else close[p] * fx
                base_a = adj[p] if hedged else adj[p] * fx
                d = pd.Series(drag, index=close.index).where(base_a.notna()).cumprod()
                close[k], adj[k] = base_c * d, base_a * d
                cols.append(k)
            gaps[name] = gap
        assets[name] = cols
        info[name] = spec
    assets[CASH] = ["153130.KS", "114260.KS", "TBILL"]
    m = build_market(close, adj, assets, local=tuple(assets))
    me = base.close.index
    keep = [c for c in base.close.columns if c not in m.close.columns and c in ("NDX_USD", "SPX_USD", "TIPX", "AGG")]
    out = Market(close=m.close.reindex(me).join(base.close[keep]), total=m.total.reindex(me).join(base.total[keep]),
                 high52=m.high52.reindex(me).join(base.high52[keep]), extra=dict(base.extra))
    real = {n: pd.Timestamp(close[s[0]].first_valid_index()) for n, s in info.items() if s}
    return out, {"spec": info, "real_start": real, "gap": gaps}


def _gap(domestic: pd.Series, proxy: pd.Series) -> float:
    """겹치는 기간의 연수익 차이(대용 − 국내). 상장 전 대용치에서 이만큼 깎는다."""
    m = pd.DataFrame({"d": domestic, "p": proxy}).resample("ME").last().dropna()
    if len(m) < 12:
        return 0.0
    yrs = (len(m) - 1) / 12
    a = (m.d.iloc[-1] / m.d.iloc[0]) ** (1 / yrs) - 1
    b = (m.p.iloc[-1] / m.p.iloc[0]) ** (1 / yrs) - 1
    return float(b - a)


# ------------------------------------------------------------------ 전략 (변형 가능)

def trend(asset, signal, n=10):
    def strat(d, ctx):
        m = ctx.m
        return {asset: 1.0} if ctx.val(m.close, signal) > ctx.val(m.sma(n), signal) else {CASH: 1.0}
    return strat


def dga(canary_n=12, def_n=6, windows=(1, 3, 6, 9, 12)):
    def strat(d, ctx):
        m = ctx.m
        i = ctx.i
        risk = (ctx.val(m.close, "TIPX") < ctx.val(m.sma(canary_n), "TIPX")
                or m.extra["div_yield"].iloc[i] < .016 or m.extra["spread"].iloc[i] < -.5)
        if not risk:
            s = sum(m.mom_total(k) for k in windows) / len(windows)
            return {max(("NDX", "SCHD"), key=lambda a: ctx.val(s, a)): 1.0}
        ratio = m.close / m.sma(def_n)
        ok = [a for a in ("BIL", "TLT", "COMM") if a in m.close and not np.isnan(ctx.val(ratio, a))]
        best = max(ok, key=lambda a: ctx.val(ratio, a))
        return {best: 1.0} if ctx.val(ratio, best) >= 1 else {CASH: 1.0}
    return strat


DAA_OFF = ("SPX", "NDX", "EFA", "EEM", "GOLD", "UST10", "TLT")

# 이름: (종류, 쓰는 자산, 평소·짧게·길게 변형을 만드는 함수, 앱 지원 여부)
P = {
    "GSM 상위2+금·채권": ("교체형", GSM2 + (CASH,), lambda v: S.gsm(cands=GSM2, top=2, sma_n=v["sma"]), True),
    "GSM 상위2 현금없음": ("교체형", GSM2 + (CASH,), lambda v: S.gsm(cands=GSM2, top=2, invest=1.0, sma_n=v["sma"]), False),
    "GSM 1위(2026)": ("교체형", ("NDX", "SPX", "WORLD", "EURO", CASH), lambda v: S.gsm(sma_n=v["sma"]), True),
    "DGA": ("교체형", ("NDX", "SCHD", "BIL", "TLT", "COMM", CASH),
            lambda v: dga(canary_n=v["sma"] + 2, def_n=v["sma"] - 4), False),
    "DAA": ("교체형", DAA_OFF + (CASH,), lambda v: S.daa(offense=DAA_OFF, defense=("UST10", CASH), top=v["top"]), False),
    "가속듀얼모멘텀": ("교체형", ("SPX", "EFA", "TLT"), lambda v: S.adm(risk=("SPX", "EFA"), bond="TLT", windows=v["win"]), False),
    "LAA 변형": ("고정+필터", ("NDX", "EURO", "SPX", "WORLD", "GOLD", "UST10", CASH),
                lambda v: S.laa_variant(sma_n=v["sma"]), True),
    "원조 LAA": ("고정+필터", ("SPX", "GOLD", "UST10", "NDX", CASH), lambda v: laa_original_kr, False),
    "황금나비": ("고정형", tuple(BUTTERFLY), lambda v: S.hold(BUTTERFLY, (12,)), True),
    "영구 포트폴리오": ("고정형", ("SPX", "TLT", "GOLD", CASH), lambda v: S.hold({"SPX": .25, "TLT": .25, "GOLD": .25, CASH: .25}, (12,)), True),
    "올웨더(간이)": ("고정형", ("SPX", "TLT", "UST10", "GOLD"), lambda v: S.hold({"SPX": .3, "TLT": .4, "UST10": .15, "GOLD": .15}, (12,)), True),
    "60/40": ("고정형", ("SPX", "UST10"), lambda v: S.hold({"SPX": .6, "UST10": .4}, (12,)), True),
    "S&P500 보유": ("단일 보유", ("SPX",), lambda v: S.hold({"SPX": 1}), True),
    "나스닥 보유": ("단일 보유", ("NDX",), lambda v: S.hold({"NDX": 1}), True),
}
ISA_ONLY = {
    "나스닥2배 SMA 추세": ("레버리지", ("QLD", CASH), lambda v: trend("QLD", "NDX_USD", v["sma"]), True),
    "S&P2배 SMA 추세": ("레버리지", ("SSO", CASH), lambda v: trend("SSO", "SPX_USD", v["sma"]), True),
    "나스닥2배 단계(2026)": ("레버리지", ("QLD", CASH), lambda v: S.ladder("QLD", "NDX_USD", 0.0, S.ISA_STEPS), True),
}
GEN = {
    "국내 주식 보유": ("단일 보유", lambda v: S.hold({"KOSPI": 1}), True),
    "국내 주식 절반 필터": ("고정+필터", lambda v: S.mix({"KOSPI": 1}, 1.0, "KOSPI", .5), False),
    "국내·미국 듀얼": ("교체형", lambda v: S.relative_momentum(("KOSPI", "SPX"), months=v["mom"]), False),
    "국내50/S&P50": ("고정형", lambda v: S.hold({"KOSPI": .5, "SPX": .5}, (12,)), True),
    "S&P500 보유": ("단일 보유", lambda v: S.hold({"SPX": 1}), True),
    "나스닥 보유": ("단일 보유", lambda v: S.hold({"NDX": 1}), True),
    "황금나비": ("고정형", lambda v: S.hold(BUTTERFLY, (12,)), True),
    "영구 포트폴리오": ("고정형", lambda v: S.hold({"SPX": .25, "TLT": .25, "GOLD": .25, CASH: .25}, (12,)), True),
    "6자산 고정": ("고정형", lambda v: S.hold(S.LAA_TARGET, (12,)), True),
    "SSO 단계(2026)": ("레버리지", lambda v: S.ladder("SSO", "SPX_USD", .70, S.SSO_STEPS), True),
    "SSO 단계+추가매수 보류": ("레버리지", lambda v: S.ladder("SSO", "SPX_USD", .70, S.SSO_STEPS, sma_exit=True), False),
    "DGA": ("교체형", lambda v: dga(canary_n=v["sma"] + 2, def_n=v["sma"] - 4), False),
}
VARIANTS = {"기본": {"sma": 10, "top": 3, "win": (1, 3, 6), "mom": 12},
            "짧게": {"sma": 8, "top": 2, "win": (1, 3), "mom": 9},
            "길게": {"sma": 12, "top": 4, "win": (1, 3, 6, 12), "mom": 12 + 3}}
REPRO = {"DGA": 0.0, "원조 LAA": 0.5}  # 재현 점수(나머지 1): DGA는 앱 성적 재현 실패, 원조 LAA는 실업률 조건 없음
CURRENT_GEN2_US = "SSO"  # 지금 일반계좌 2에 들고 있는 미국 ETF


def account_series(markets, dom_info, variant) -> dict:
    """{(계좌군, 이름): {"krw": ret, "usd": ret, "turn": 연 회전율}}"""
    out = {}
    v = VARIANTS[variant]
    for grp, menu in (("pen", P), ("isa", {**P, **ISA_ONLY})):
        for name, (kind, assets, make, _) in menu.items():
            if any(dom_info["spec"].get(a, True) is None for a in assets if a != CASH):
                continue  # G6 탈락: 호환 국내 ETF 없음
            try:
                rk = run(make(v), markets["dom"], STARTS["krw"], END)
                ru = run(make(v), markets["usd"], STARTS["usd"], END)
            except (ValueError, KeyError):
                continue
            out[(grp, name)] = {"krw": rk["ret"], "usd": ru["ret"], "turn": rk["turnover"].sum() / (len(rk) / 12)}
    for name, (kind, make, _) in GEN.items():
        try:
            rk = run(make(v), markets["krw"], STARTS["krw"], END)
            ru = run(make(v), markets["usd"], STARTS["usd"], END)
        except (ValueError, KeyError):
            continue
        out[("gen", name)] = {"krw": after_tax(rk), "usd": after_tax(ru), "turn": rk["turnover"].sum() / (len(rk) / 12)}
    for name, w in (("GOLD", {"GOLD": 1}), ("CASH", {CASH: 1})):
        out[("fix", name)] = {"krw": run(S.hold(w), markets["krw"], STARTS["krw"], END)["ret"],
                              "usd": run(S.hold(w), markets["usd"], STARTS["usd"], END)["ret"], "turn": 0.0}
    return out


def kind_of(grp, name):
    if grp == "gen":
        return GEN[name][0]
    return {**P, **ISA_ONLY}[name][0]


def app_ok(grp, name):
    if grp == "gen":
        return GEN[name][2]
    return {**P, **ISA_ONLY}[name][3]


def lin(x, best, worst, pts):
    t = (x - worst) / (best - worst)
    return pts * min(1.0, max(0.0, t))


ACC = ["PEN_FREE", "PEN_TAX", "ISA", "GEN1", "GEN2"]
GRP = {"PEN_FREE": "pen", "PEN_TAX": "pen", "ISA": "isa", "GEN1": "gen", "GEN2": "gen"}


def portfolio_paths(series, combo, w, key):
    idx = series[("fix", "GOLD")][key].index
    vals = {}
    for a, n in zip(ACC, combo):
        vals[a] = w[a] * (1 + series[(GRP[a], n)][key].reindex(idx)).cumprod()
    vals["GOLD"] = w["GOLD"] * (1 + series[("fix", "GOLD")][key]).cumprod()
    vals["CASH"] = w["CASH"] * (1 + series[("fix", "CASH")][key]).cumprod()
    return pd.DataFrame(vals)


def score(series, combo, w, dom_info, approx_assets, variants=None):
    V = portfolio_paths(series, combo, w, "krw")
    tot = V.sum(axis=1)
    r = tot.pct_change()
    r.iloc[0] = tot.iloc[0] - 1
    Vu = portfolio_paths(series, combo, w, "usd").sum(axis=1)
    ru = Vu.pct_change()
    ru.iloc[0] = Vu.iloc[0] - 1
    k = int((r.index <= pd.Timestamp(SPLIT)).sum())
    arr = r.values[None, :]
    cg, md, worst = seg_stats(arr)
    c1, m1, _ = seg_stats(arr[:, :k])
    c2, m2, _ = seg_stats(arr[:, k:])
    cu, mu, _ = seg_stats(ru.values[None, :])
    res = {"원화 연수익": cg[0], "원화 MDD": md[0], "앞 MDD": m1[0], "뒤 MDD": m2[0], "최악12개월": worst[0],
           "앞 연수익": c1[0], "뒤 연수익": c2[0], "달러 연수익": cu[0], "달러 MDD": mu[0]}
    res["관문"] = (min(md[0], m1[0], m2[0]) >= -.20) and (mu[0] >= -.30)
    names = list(combo)
    kinds = [kind_of(GRP[a], n) for a, n in zip(ACC, combo)]
    nd = len(set(names))
    nk = len(set(kinds))
    a1 = {5: 5, 4: 3}.get(nd, 0) + {5: 5, 4: 4, 3: 2}.get(nk, 0)
    rets = pd.DataFrame({a: series[(GRP[a], n)]["krw"] for a, n in zip(ACC, combo)})
    rets["GOLD"] = series[("fix", "GOLD")]["krw"]
    C = rets.corr().values
    wt = np.array([w[a] for a in ACC] + [w["GOLD"]])
    num = den = 0.0
    for i, j in itertools.combinations(range(6), 2):
        num += wt[i] * wt[j] * C[i, j]
        den += wt[i] * wt[j]
    corr = num / den
    a2 = lin(corr, .15, .35, 15)
    acc_r = V.drop(columns="CASH").pct_change()
    share = V.drop(columns="CASH").shift(1).div(V.drop(columns="CASH").shift(1).sum(axis=1), axis=0)
    bad = r <= -.03
    loss = ((acc_r < 0) * share).sum(axis=1)[bad]
    co_loss = float(loss.mean()) if len(loss) else 0.0
    a3 = lin(co_loss, .5, .9, 10)
    b1 = lin(md[0], -.10, -.20, 10)
    b2 = lin(mu[0], -.20, -.30, 8)
    b3 = lin(worst[0], -.05, -.20, 7)
    robust = min(c1[0], c2[0], cu[0])
    c = lin(robust, .10, .06, 15)
    d2 = d2_of(combo, w, dom_info)
    tw = sum(w[a] for a in ACC)
    # E
    turn = sum(w[a] * series[(GRP[a], n)]["turn"] for a, n in zip(ACC, combo)) / (tw + w["GOLD"])
    e1 = lin(turn, .5, 3.0, 4)
    gen_w = w["GEN1"] + w["GEN2"]
    sold = 0.0 if combo[4].startswith("SSO") else w["GEN2"] / gen_w
    gen_turn = (w["GEN1"] * series[("gen", combo[3])]["turn"] + w["GEN2"] * series[("gen", combo[4])]["turn"]) / gen_w
    e2 = 3 * max(0.0, 1 - sold - min(1.0, gen_turn))
    amb = sum(1 for a, n in zip(ACC, combo) if GRP[a] != "gen" and any(x in approx_assets for x in {**P, **ISA_ONLY}[n][1]))
    new = len({n for a, n in zip(ACC, combo) if not app_ok(GRP[a], n)})
    e3 = max(0.0, 3 - amb - .5 * new)
    res.update({"평균 상관": corr, "동반 손실": co_loss, "견고수익": robust, "회전율": turn,
                "A1": a1, "A2": a2, "A3": a3, "B1": b1, "B2": b2, "B3": b3, "C": c, "D2": d2, "E1": e1, "E2": e2, "E3": e3})
    if variants is not None:
        cs, ok = [], True
        for vs in variants.values():
            Vv = portfolio_paths(vs, combo, w, "krw").sum(axis=1)
            rv = Vv.pct_change()
            rv.iloc[0] = Vv.iloc[0] - 1
            av = rv.values[None, :]
            cgv, mdv, _ = seg_stats(av)
            _, m1v, _ = seg_stats(av[:, :k])
            _, m2v, _ = seg_stats(av[:, k:])
            cs.append(cgv[0])
            ok &= min(mdv[0], m1v[0], m2v[0]) >= -.20
        spread = max(abs(x - cg[0]) for x in cs)
        res["D1"] = 0.0 if not ok else lin(spread, .01, .02, 8)
        res["설정 변화폭"] = spread
    res["점수(D1 제외)"] = a1 + a2 + a3 + b1 + b2 + b3 + c + d2 + e1 + e2 + e3
    if "D1" in res:
        res["총점"] = res["점수(D1 제외)"] + res["D1"]
    return res


def d2_of(combo, w, dom_info) -> float:
    """D2: 재현 4점 + 실제 국내 ETF 시세 기간 비율 3점 (계좌 비중 가중)."""
    period = (pd.Timestamp(STARTS["krw"]), pd.Timestamp(END))
    span = (period[1] - period[0]).days
    rep = real = 0.0
    tw = sum(w[a] for a in ACC)
    for a, n in zip(ACC, combo):
        rep += w[a] * REPRO.get(n, 1.0)
        if GRP[a] == "gen":
            real += w[a]
            continue
        assets = [x for x in {**P, **ISA_ONLY}[n][1] if x != CASH and dom_info["spec"].get(x)]
        fr = [max(0, (period[1] - max(period[0], dom_info["real_start"][x])).days) / span for x in assets]
        real += w[a] * (np.mean(fr) if fr else 1.0)
    return 4 * rep / tw + 3 * real / tw


def prefilter(series, names, w, approx_assets, dom_info) -> pd.DataFrame:
    """모든 조합을 빠르게 계산: 관문(G1·G2)과 예비 점수(A3·D1 제외)."""
    idx = series[("fix", "GOLD")]["krw"].index
    idu = series[("fix", "GOLD")]["usd"].index
    k = int((idx <= pd.Timestamp(SPLIT)).sum())

    def paths(key, ix):
        V = {g: {n: (1 + series[(g, n)][key].reindex(ix)).cumprod().values for n in names[g]} for g in names}
        fixed = w["GOLD"] * (1 + series[("fix", "GOLD")][key]).cumprod().values + \
            w["CASH"] * (1 + series[("fix", "CASH")][key]).cumprod().values
        return V, fixed
    Vk, fk = paths("krw", idx)
    Vu, fu = paths("usd", idu)
    gen = names["gen"]
    pairs = list(itertools.product(gen, repeat=2))
    Gk = np.stack([w["GEN1"] * Vk["gen"][a] + w["GEN2"] * Vk["gen"][b] for a, b in pairs])
    Gu = np.stack([w["GEN1"] * Vu["gen"][a] + w["GEN2"] * Vu["gen"][b] for a, b in pairs])
    # 상관행렬
    keys = [("pen", n) for n in names["pen"]] + [("isa", n) for n in names["isa"]] + [("gen", n) for n in gen] + [("fix", "GOLD")]
    pos = {kk: i for i, kk in enumerate(keys)}
    C = pd.DataFrame({i: series[kk]["krw"] for i, kk in enumerate(keys)}).corr().values
    wt = np.array([w[a] for a in ACC] + [w["GOLD"]])
    tw = sum(w[a] for a in ACC)
    gen_w = w["GEN1"] + w["GEN2"]
    rows = []

    def stat(val):
        val = np.concatenate([np.ones((len(val), 1)), val], axis=1)
        return val[:, 1:] / val[:, :-1] - 1
    for pf, pt, isa in itertools.product(names["pen"], names["pen"], names["isa"]):
        bk = w["PEN_FREE"] * Vk["pen"][pf] + w["PEN_TAX"] * Vk["pen"][pt] + w["ISA"] * Vk["isa"][isa] + fk
        bu = w["PEN_FREE"] * Vu["pen"][pf] + w["PEN_TAX"] * Vu["pen"][pt] + w["ISA"] * Vu["isa"][isa] + fu
        rk = stat(bk[None, :] + Gk)
        ru = stat(bu[None, :] + Gu)
        cg, md, worst = seg_stats(rk)
        c1, m1, _ = seg_stats(rk[:, :k])
        c2, m2, _ = seg_stats(rk[:, k:])
        cu, mu, _ = seg_stats(ru)
        ok = (np.minimum(np.minimum(md, m1), m2) >= -.20) & (mu >= -.30)
        for j in np.nonzero(ok)[0]:
            g1, g2 = pairs[j]
            combo = (pf, pt, isa, g1, g2)
            grp = ["pen", "pen", "isa", "gen", "gen"]
            kinds = [kind_of(g, n) for g, n in zip(grp, combo)]
            nd, nk = len(set(combo)), len(set(kinds))
            a1 = {5: 5, 4: 3}.get(nd, 0) + {5: 5, 4: 4, 3: 2}.get(nk, 0)
            ids = [pos[(g, n)] for g, n in zip(grp, combo)] + [pos[("fix", "GOLD")]]
            num = den = 0.0
            for a, b in itertools.combinations(range(6), 2):
                num += wt[a] * wt[b] * C[ids[a], ids[b]]
                den += wt[a] * wt[b]
            a2 = lin(num / den, .15, .35, 15)
            b1 = lin(md[j], -.10, -.20, 10)
            b2 = lin(mu[j], -.20, -.30, 8)
            b3 = lin(worst[j], -.05, -.20, 7)
            c = lin(min(c1[j], c2[j], cu[j]), .10, .06, 15)
            turn = sum(w[a] * series[(g, n)]["turn"] for a, g, n in zip(ACC, grp, combo)) / (tw + w["GOLD"])
            e1 = lin(turn, .5, 3.0, 4)
            sold = 0.0 if g2.startswith("SSO") else w["GEN2"] / gen_w
            gt = (w["GEN1"] * series[("gen", g1)]["turn"] + w["GEN2"] * series[("gen", g2)]["turn"]) / gen_w
            e2 = 3 * max(0.0, 1 - sold - min(1.0, gt))
            amb = sum(1 for g, n in zip(grp, combo) if g != "gen" and any(x in approx_assets for x in {**P, **ISA_ONLY}[n][1]))
            new = len({n for g, n in zip(grp, combo) if not app_ok(g, n)})
            e3 = max(0.0, 3 - amb - .5 * new)
            rows.append((*combo, a1 + a2 + b1 + b2 + b3 + c + d2_of(combo, w, dom_info) + e1 + e2 + e3))
    total = len(names["pen"]) ** 2 * len(names["isa"]) * len(pairs)
    df = pd.DataFrame(rows, columns=ACC + ["예비 점수"])
    df.attrs["total"] = total
    return df


NAMED = {
    "F1 (2027 확정)": ("GSM 상위2+금·채권", "LAA 변형", "나스닥2배 SMA 추세", "국내 주식 보유", "S&P500 보유"),
    "2026 조합": ("GSM 1위(2026)", "LAA 변형", "나스닥2배 단계(2026)", "국내 주식 보유", "SSO 단계(2026)"),
    "b (연금 GSM 둘+듀얼)": ("GSM 상위2 현금없음", "GSM 상위2 현금없음", "나스닥2배 SMA 추세", "국내·미국 듀얼", "S&P500 보유"),
    "P9": ("DGA", "DAA", "나스닥2배 SMA 추세", "국내 주식 보유", "황금나비"),
    "P7": ("DGA", "가속듀얼모멘텀", "나스닥2배 SMA 추세", "국내 주식 보유", "황금나비"),
    "P10": ("DAA", "가속듀얼모멘텀", "나스닥2배 SMA 추세", "국내 주식 보유", "황금나비"),
    "P1": ("DGA", "가속듀얼모멘텀", "나스닥2배 SMA 추세", "국내 주식 보유", "SSO 단계+추가매수 보류"),
}


def main(path: str, top: int = 25) -> None:
    acc = json.loads(open(path, encoding="utf-8").read())
    tot = sum(acc.values())
    w = {k: v / tot for k, v in acc.items()}
    base = {"krw": _extend(prepare(krw=True), True), "usd": _extend(prepare(krw=False), False)}
    tick = pd.read_csv("backtest/data/tickers.csv")
    available = set(tick.loc[tick["rows"] > 0, "ticker"])
    dom, info = domestic_market(base["krw"], base["usd"], available)
    markets = {"krw": base["krw"], "usd": base["usd"], "dom": dom}

    print("## 국내 ETF 호환표 (연금·ISA)\n")
    rows = []
    for a, spec in DOMESTIC.items():
        if spec is None or spec[0] not in available:
            rows.append({"자산": a, "국내 ETF": "없음 → 이 자산을 쓰는 전략은 연금·ISA에서 G6 탈락"})
            continue
        code, label, hedged, approx, _ = spec
        nm = tick.set_index("ticker").loc[code, "name"]
        rows.append({"자산": a, "국내 ETF": f"{label} ({code[:6]})", "Yahoo 이름": nm, "헤지": "H" if hedged else "환노출",
                     "근사": "근사" if approx else "", "실제 시세 시작": str(info["real_start"][a].date()),
                     "대용치와 연 차이(상장 전 차감)": f"{info['gap'].get(a, 0) * 100:.1f}%p"})
    print(pd.DataFrame(rows).to_markdown(index=False))
    approx_assets = {a for a, s in DOMESTIC.items() if s and s[3]}

    series = {v: account_series(markets, info, v) for v in VARIANTS}
    base_s = series["기본"]
    names = {g: sorted({n for (gg, n) in base_s if gg == g}) for g in ("pen", "isa", "gen")}
    dropped = sorted(set(P) - set(names["pen"]))
    print(f"\nG6 탈락(연금·ISA에서 못 씀): {dropped}")
    # 단독 성적: 국내 ETF vs 미국 대용
    solo = {}
    for (g, n), s in base_s.items():
        if g == "fix":
            continue
        rr = s["krw"]
        v = (1 + rr).cumprod()
        solo[f"{n} [{ {'pen': '연금', 'isa': 'ISA', 'gen': '일반'}[g] }]"] = {
            "원화 연수익": v.iloc[-1] ** (12 / len(rr)) - 1, "원화 MDD": (v / v.cummax() - 1).min(), "연 회전율": s["turn"]}
    print("\n## 전략 단독 (원화 2005~, 연금·ISA는 국내 ETF 기준)\n")
    print(pd.DataFrame(solo).T.map(lambda x: f"{x * 100:.1f}%").to_markdown())

    pre = prefilter(base_s, names, w, approx_assets, info)
    print(f"\n전체 조합: {pre.attrs['total']:,}, 관문 통과: {len(pre):,}")
    var = {k: v for k, v in series.items() if k != "기본"}
    pre = pre.sort_values("예비 점수", ascending=False)
    full, totals = {}, {}

    def nd(c):
        if c not in full:
            full[c] = score(base_s, c, w, info, approx_assets)
        return full[c]["점수(D1 제외)"]

    def total(c):
        if c not in totals:
            totals[c] = score(base_s, c, w, info, approx_assets, variants=var)["총점"]
        return totals[c]
    # 1차: 예비 상위 4,000개로 기준 총점을 잡는다
    for c in pre[ACC].head(4000).itertuples(index=False):
        nd(tuple(c))
    for c in sorted(full, key=lambda c: -full[c]["점수(D1 제외)"])[:top]:
        total(c)
    best = max(totals.values())
    # 2차: A3(최대 10)·D1(최대 8)을 다 받아도 best에 못 미치는 조합은 제외하고 나머지를 모두 정밀 계산
    cand = pre[pre["예비 점수"] + 18 >= best]
    for c in cand[ACC].itertuples(index=False):
        nd(tuple(c))
    for c in [c for c in full if full[c]["점수(D1 제외)"] + 8 >= best]:
        total(c)
    best = max(totals.values())
    print(f"정밀 계산 {len(full):,}개, D1까지 계산 {len(totals):,}개. 남은 조합은 A3·D1 만점을 받아도 1위({best:.1f})보다 낮다.")
    df = pd.DataFrame([{**dict(zip(ACC, c)), **full[c], "총점": totals[c]} for c in totals]).sort_values("총점", ascending=False)
    pick = [tuple(r) for r in df[ACC].head(top).values]
    for c in NAMED.values():
        if c not in pick:
            pick.append(c)
    final = []
    for label, c in NAMED.items():
        bad = [n for g, n in zip(["pen", "pen", "isa"], c[:3]) if (g, n) not in base_s]
        if bad:
            print(f"- {label}: G6 탈락 ({', '.join(bad)}를 연금·ISA에서 할 국내 ETF가 없음)")
    pick = [c for c in pick if all((g, n) in base_s for g, n in zip(["pen", "pen", "isa", "gen", "gen"], c))]
    for c in pick:
        s = score(base_s, c, w, info, approx_assets, variants=var)
        label = next((k for k, v in NAMED.items() if v == c), "")
        if not s["관문"]:
            label += " (G1·G2 탈락)"
        final.append({"이름": label, **dict(zip(ACC, c)), **s})
    out = pd.DataFrame(final).sort_values("총점", ascending=False)
    out.to_pickle(path + ".eval.pkl")
    show = ["이름", *ACC, "총점", "관문", "A1", "A2", "A3", "B1", "B2", "B3", "C", "D1", "D2", "E1", "E2", "E3",
            "원화 연수익", "원화 MDD", "최악12개월", "달러 MDD", "견고수익", "평균 상관", "동반 손실", "회전율", "설정 변화폭"]
    t = out[show].copy()
    for c in ["원화 연수익", "원화 MDD", "최악12개월", "달러 MDD", "견고수익", "동반 손실", "회전율", "설정 변화폭"]:
        t[c] = t[c].map(lambda x: f"{x * 100:.1f}%")
    for c in ["총점", "A1", "A2", "A3", "B1", "B2", "B3", "C", "D1", "D2", "E1", "E2", "E3", "평균 상관"]:
        t[c] = t[c].map(lambda x: f"{x:.1f}" if c != "평균 상관" else f"{x:.2f}")
    print("\n## 최종 점수 (관문 통과 상위 + 지금까지 나온 후보)\n")
    print(t.rename(columns={"PEN_FREE": "연금(비과세)", "PEN_TAX": "연금(과세)", "GEN1": "일반1", "GEN2": "일반2"})
          .to_markdown(index=False))


if __name__ == "__main__":
    main(*sys.argv[1:])
