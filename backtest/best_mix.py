"""계좌별 전략 짝을 모두 풀고, 계좌마다 살 수 있는 상품·세금만 지켜 조합을 찾는다.

python -m backtest.best_mix 비중.json

비중.json (저장소에 올리지 않는다):
  {"PEN_FREE": 금액, "PEN_TAX": 금액, "ISA": 금액, "GEN1": 금액, "GEN2": 금액, "GOLD": 금액, "CASH": 금액}

두 가지 시험을 함께 본다.
- 원화 2005-01~2026-09: 실제와 가까운 계산. 앞 절반(~2015)과 뒤 절반(2016~)으로 나눠 본다.
- 달러 1997-04~2026-09: 위기 때 원화 약세의 도움이 없는 "방패 없는" 시험. 국내 주식은 EWY(2000-05 전은 신흥국 펀드).
계좌 규칙: 연금저축 = 국내 상장 ETF, 레버리지 불가, 세금 0. ISA = 레버리지 가능, 세금 0.
일반계좌 = 국내 주식·미국 ETF, 미국 ETF 이익 22%·현금 이자 15.4%(optimize.after_tax 근사).
금 계좌는 금 보유, 별도 현금은 현금으로 고정한다. 계좌 사이에는 돈을 옮기지 않는다.
"""
from __future__ import annotations

import itertools
import json
import sys

import numpy as np
import pandas as pd

from backtest import strategies as S
from backtest.engine import CASH, Market, build_market, run
from backtest.optimize import after_tax, laa_original_kr
from backtest.run import END, prepare

LIMIT = -0.20
PERIODS = {"krw": ("2005-01-31", "2015-12-31"), "usd": ("1997-04-30", None)}


def trend(asset: str, signal: str, invest: float = 1.0):
    def strat(d, ctx):
        m = ctx.m
        up = ctx.val(m.close, signal) > ctx.val(m.sma(10), signal)
        return {asset: invest, CASH: 1 - invest} if up else {CASH: 1.0}
    return strat


def markets() -> dict:
    out = {"krw": prepare(krw=True)}
    m = prepare(krw=False)
    d = m.extra
    k = build_market(d["close_d"], d["adj_d"], {"KOSPI": ["EWY", "VEIEX"], "SPX_USD": ["SPY", "VFINX"],
                                               "NDX_USD": ["QQQ", "^NDX"]})
    out["usd"] = Market(close=m.close.join(k.close), total=m.total.join(k.total),
                        high52=m.high52.join(k.high52), extra=d)
    return out


GSM2 = ("NDX", "SPX", "WORLD", "EURO", "GOLD", "UST10")


def pension_menu() -> dict:
    off = ("SPX", "NDX", "EFA", "EEM", "GOLD", "UST10", "TLT")
    return {
        "GSM 1위(2026)": S.gsm(),
        "GSM 상위2+금·채권(2027)": S.gsm(cands=GSM2, top=2),
        "GSM 상위2+금·채권 현금없음": S.gsm(cands=GSM2, top=2, invest=1.0),
        "LAA 변형": S.laa_variant(),
        "6자산 고정": S.hold(S.LAA_TARGET, S.QUARTER_MONTHS),
        "원조 LAA": laa_original_kr,
        "DAA": S.daa(offense=off, defense=("UST10", CASH), top=3),
        "GTAA": S.gtaa(assets=("SPX", "EFA", "EEM", "UST10", "GOLD")),
        "영구 포트폴리오": S.hold({"SPX": .25, "TLT": .25, "GOLD": .25, CASH: .25}, (12,)),
        "60/40": S.hold({"SPX": .6, "UST10": .4}, (12,)),
        "올웨더(간이)": S.hold({"SPX": .3, "TLT": .4, "UST10": .15, "GOLD": .15}, (12,)),
        "S&P500 보유": S.hold({"SPX": 1}),
        "나스닥 보유": S.hold({"NDX": 1}),
        "나스닥 SMA 추세": trend("NDX", "NDX"),
    }


def isa_menu() -> dict:
    return {
        **pension_menu(),
        "나스닥2배 단계(2026)": S.ladder("QLD", "NDX_USD", 0.0, S.ISA_STEPS),
        "나스닥2배 단계+SMA현금": S.ladder("QLD", "NDX_USD", 0.0, S.ISA_STEPS, sma_sell=True),
        "나스닥2배 SMA 추세(2027)": trend("QLD", "NDX_USD"),
        "S&P2배 SMA 추세": trend("SSO", "SPX_USD"),
        "나스닥2배 추세 50%": trend("QLD", "NDX_USD", .5),
        "현금 대기": S.hold({CASH: 1}),
    }


def general_menu() -> dict:
    return {
        "국내 주식 보유": S.hold({"KOSPI": 1}),
        "국내 주식 절반 필터": S.mix({"KOSPI": 1}, 1.0, "KOSPI", .5),
        "국내 주식 SMA 추세": trend("KOSPI", "KOSPI"),
        "국내·미국 듀얼": S.relative_momentum(("KOSPI", "SPX")),
        "국내50/S&P50": S.hold({"KOSPI": .5, "SPX": .5}, (12,)),
        "S&P500 보유": S.hold({"SPX": 1}),
        "나스닥 보유": S.hold({"NDX": 1}),
        "SSO 단계(2026)": S.ladder("SSO", "SPX_USD", .70, S.SSO_STEPS),
        "SSO 단계+추가매수 보류": S.ladder("SSO", "SPX_USD", .70, S.SSO_STEPS, sma_exit=True),
        "S&P2배 SMA 추세": trend("SSO", "SPX_USD"),
        "6자산 고정(미국 ETF)": S.hold(S.LAA_TARGET, (12,)),
        "LAA 변형(미국 ETF)": S.laa_variant(),
        "영구(미국 ETF)": S.hold({"SPX": .25, "TLT": .25, "GOLD": .25, CASH: .25}, (12,)),
    }


def curves(menu: dict, m: Market, start: str, taxed: bool) -> dict:
    out = {}
    for name, fn in menu.items():
        try:
            res = run(fn, m, start, END)
        except (ValueError, KeyError):
            continue
        out[name] = after_tax(res) if taxed else res["ret"]
    return out


def seg_stats(r: np.ndarray) -> tuple:
    """r: (조합, 개월) 월수익률 → CAGR, MDD, 최악의 12개월."""
    v = np.cumprod(1 + r, axis=1)
    v = np.concatenate([np.ones((len(v), 1)), v], axis=1)
    cagr = v[:, -1] ** (12 / r.shape[1]) - 1
    mdd = (v / np.maximum.accumulate(v, axis=1) - 1).min(axis=1)
    worst = (v[:, 12:] / v[:, :-12] - 1).min(axis=1)
    return cagr, mdd, worst


def main(path: str) -> None:
    acc = json.loads(open(path, encoding="utf-8").read())
    total = sum(acc.values())
    w = {k: v / total for k, v in acc.items()}
    M = markets()
    data = {}
    for key, m in M.items():
        start = PERIODS[key][0]
        data[key] = {
            "pen": curves(pension_menu(), m, start, False),
            "isa": curves(isa_menu(), m, start, False),
            "gen": curves(general_menu(), m, start, True),
            "gold": curves({"g": S.hold({"GOLD": 1})}, m, start, False)["g"],
            "cash": curves({"c": S.hold({CASH: 1})}, m, start, False)["c"],
        }
    names = {g: [n for n in data["krw"][g] if n in data["usd"][g]] for g in ("pen", "isa", "gen")}
    dropped = {g: sorted(set(data["krw"][g]) - set(names[g])) for g in names}
    print("계좌 비중: " + ", ".join(f"{k} {v * 100:.1f}%" for k, v in w.items()))
    print(f"후보 전략: 연금 {len(names['pen'])}, ISA {len(names['isa'])}, 일반 {len(names['gen'])}"
          f" (달러 기간 자료 부족으로 뺀 것: {dropped})")

    def value_paths(key):
        d = data[key]
        idx = d["gold"].index
        V = {g: np.stack([(1 + d[g][n].reindex(idx)).cumprod().values for n in names[g]]) for g in names}
        fixed = w["GOLD"] * (1 + d["gold"]).cumprod().values + w["CASH"] * (1 + d["cash"]).cumprod().values
        return V, fixed, idx

    pairs = list(itertools.product(range(len(names["gen"])), repeat=2))
    combos = list(itertools.product(range(len(names["pen"])), range(len(names["pen"])), range(len(names["isa"]))))
    cols = {}
    for key in ("krw", "usd"):
        V, fixed, idx = value_paths(key)
        G = np.stack([w["GEN1"] * V["gen"][a] + w["GEN2"] * V["gen"][b] for a, b in pairs])
        split = PERIODS["krw"][1]
        k = int((idx <= pd.Timestamp(split)).sum()) if key == "krw" else None
        res = {s: [] for s in ("cagr", "mdd", "worst", "c1", "m1", "c2", "m2")}
        for a, b, c in combos:
            base = w["PEN_FREE"] * V["pen"][a] + w["PEN_TAX"] * V["pen"][b] + w["ISA"] * V["isa"][c] + fixed
            val = base[None, :] + G
            val = np.concatenate([np.ones((len(val), 1)), val], axis=1)
            r = val[:, 1:] / val[:, :-1] - 1
            cg, md, wo = seg_stats(r)
            res["cagr"].append(cg); res["mdd"].append(md); res["worst"].append(wo)
            if k:
                c1, m1, _ = seg_stats(r[:, :k]); c2, m2, _ = seg_stats(r[:, k:])
                res["c1"].append(c1); res["m1"].append(m1); res["c2"].append(c2); res["m2"].append(m2)
        for s, v in res.items():
            if v:
                cols[f"{key}_{s}"] = np.concatenate(v)
    rows = [(a, b, c, g1, g2) for a, b, c in combos for g1, g2 in pairs]
    df = pd.DataFrame(rows, columns=["pf", "pt", "isa", "g1", "g2"])
    for c, v in cols.items():
        df[c] = v
    df["연금(비과세)"] = df.pf.map(lambda i: names["pen"][i])
    df["연금(과세)"] = df.pt.map(lambda i: names["pen"][i])
    df["ISA"] = df.isa.map(lambda i: names["isa"][i])
    df["일반1"] = df.g1.map(lambda i: names["gen"][i])
    df["일반2"] = df.g2.map(lambda i: names["gen"][i])
    df["견고수익"] = df[["krw_c1", "krw_c2", "usd_cagr"]].min(axis=1)
    df["최악MDD"] = df[["krw_mdd", "usd_mdd"]].min(axis=1)
    df.to_pickle(path + ".best.pkl")
    report(df)


ACCTS = ["연금(비과세)", "연금(과세)", "ISA", "일반1", "일반2"]


def pct(t: pd.DataFrame, extra=()) -> pd.DataFrame:
    show = ACCTS + ["krw_cagr", "krw_mdd", "krw_c1", "krw_c2", "usd_cagr", "usd_mdd", *extra]
    t = t[show].copy()
    for c in show[5:]:
        t[c] = t[c].map(lambda v: f"{v * 100:.1f}%")
    return t.rename(columns={"krw_cagr": "원화 연수익", "krw_mdd": "원화 MDD", "krw_c1": "원화 앞", "krw_c2": "원화 뒤",
                             "usd_cagr": "달러 연수익", "usd_mdd": "달러 MDD"})


def report(df: pd.DataFrame, top: int = 12) -> None:
    print(f"조합 수: {len(df):,}\n")
    cur = df[(df["연금(비과세)"] == "GSM 상위2+금·채권(2027)") & (df["연금(과세)"] == "LAA 변형") &
             (df.ISA == "나스닥2배 SMA 추세(2027)") & (df.일반1 == "국내 주식 보유") & (df.일반2 == "S&P500 보유")]
    old = df[(df["연금(비과세)"] == "GSM 1위(2026)") & (df["연금(과세)"] == "LAA 변형") &
             (df.ISA == "나스닥2배 단계(2026)") & (df.일반1 == "국내 주식 보유") & (df.일반2 == "SSO 단계(2026)")]
    print("## 기준: 2026 조합과 2027 조합(F1)\n")
    print(pct(pd.concat([old, cur])).to_markdown(index=False))
    ok = df[(df.krw_mdd >= LIMIT) & (df.krw_m1 >= LIMIT) & (df.krw_m2 >= LIMIT)]
    print(f"\n원화 최대 하락 -20% 이내(앞·뒤 절반 모두): {len(ok):,}개 ({len(ok) / len(df) * 100:.0f}%)")
    for title, lim in [("A. 방패 없는 시험(달러)도 -25% 이내", -.25), ("B. 달러 -30% 이내", -.30), ("C. 달러 제한 없음", -1)]:
        band = ok[ok.usd_mdd >= lim]
        print(f"\n## {title}: {len(band):,}개, 견고수익(원화 앞·뒤·달러 중 가장 낮은 연수익) 상위\n")
        if band.empty:
            continue
        print(pct(band.sort_values("견고수익", ascending=False).head(top), ["견고수익"]).to_markdown(index=False))
        best = band.sort_values("견고수익", ascending=False).head(max(50, len(band) // 100))
        freq = {n: {k: f"{v * 100:.0f}%" for k, v in best[n].value_counts(normalize=True).head(3).items()} for n in ACCTS}
        print(f"\n상위 {len(best)}개에 자주 나온 전략:")
        for n, f in freq.items():
            print(f"- {n}: {f}")
    # 과최적화 점검
    df["뒤순위"] = df.krw_c2.rank(ascending=False, pct=True)
    fb = ok.sort_values("krw_c1", ascending=False).head(100)
    print(f"\n과최적화 점검: 원화 앞 절반 수익 상위 100개의 뒤 절반 순위 중간값 상위 {df.loc[fb.index, '뒤순위'].median() * 100:.0f}%")
    print("\n## 계좌별 전략 평균 효과 (원화 -20% 이내 조합 안에서, 다른 계좌는 섞어서)\n")
    for n in ACCTS:
        g = ok.groupby(n)[["krw_cagr", "krw_mdd", "usd_mdd", "견고수익"]].mean().sort_values("견고수익", ascending=False)
        cnt = ok[n].value_counts() / df[n].value_counts()
        g["-20% 통과율"] = cnt.reindex(g.index)
        print(f"### {n}\n")
        print(g.map(lambda v: f"{v * 100:.1f}%").to_markdown())
        print()


if __name__ == "__main__":
    main(*sys.argv[1:])
