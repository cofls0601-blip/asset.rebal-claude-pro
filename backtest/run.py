"""백테스트 실행: python -m backtest.run

결과는 backtest/results/ 에 CSV와 요약 마크다운으로 저장한다.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from backtest import strategies as S
from backtest.engine import CASH, DATA_DIR, Market, build_market, leveraged, load_daily, run, stats, yearly

OUT = Path(__file__).resolve().parent / "results"
END = "2026-09-30"           # 마지막으로 끝난 달
LONG_START = "2000-01-31"    # 닷컴 하락 포함 (일부 자산은 대용치)
COMMON_START = "2007-03-31"  # 모든 비교 자산의 실제 ETF가 있는 시점 이후

# 이름: [우선 ETF, 그 전 기간을 이어 붙일 대용치...]
ASSETS = {
    "NDX": ["QQQ", "^NDX"],
    "SPX": ["SPY", "VFINX"],
    "WORLD": ["URTH", "ACWI", "MIX_WORLD"],
    "EURO": ["FDD", "FEZ", "EZU", "VEURX"],  # TIGER 유로스탁스배당30에 가까운 FDD 우선
    "EFA": ["EFA", "MIX_EAFE"],
    "EEM": ["EEM", "VEIEX"],
    "EWJ": "EWJ",
    "IWM": "IWM",
    "REIT": "VNQ",
    "DBC": "DBC",
    "GOLD": ["GLD", "GC=F", "GOLD_M"],
    "UST10": ["IEF", "VFITX"],
    "TLT": ["TLT", "VUSTX"],
    "SHY": "SHY",
    "AGG": ["AGG", "VFITX"],
    "LQD": "LQD",
    "HYG": ["HYG", "VWEHX"],
    "TIP": "TIP",
}


def prepare(data_dir: Path = DATA_DIR, krw: bool = False) -> Market:
    """krw=True면 모든 해외 자산을 원/달러로 환산하고, 현금은 원화 단기채 ETF로 바꾼다.
    SSO·ISA 신호용 SPY·QQQ 달러 가격은 SPX_USD·NDX_USD로 따로 남긴다."""
    close, adj = load_daily(data_dir)
    close = close[close.index <= pd.Timestamp(END)]
    adj = adj[adj.index <= pd.Timestamp(END)]
    # 현금: 3개월 국채 수익률로 매일 이자를 붙인다.
    irx = close["^IRX"].dropna()
    cash_d = (irx / 100 / 252).reindex(close.index).ffill()
    cash_idx = (1 + cash_d.fillna(0)).cumprod() * 100
    # 대용치 합성
    for frame in (close, adj):
        eafe = _blend(frame, {"VEURX": .7, "EWJ": .3})
        frame["MIX_EAFE"] = eafe
        efa = _splice_one(frame["EFA"], eafe)
        spx = _splice_one(frame["SPY"], frame["VFINX"])
        frame["MIX_WORLD"] = _blend(pd.DataFrame({"a": spx, "b": efa}), {"a": .6, "b": .4})
    g = pd.read_csv(data_dir / "gold_monthly.csv")
    g.index = pd.to_datetime(g["Date"]) + pd.offsets.MonthEnd(0)
    g = g["Price"]
    g = g[g.index >= "1995-01-01"]
    close = close.reindex(close.index.union(g.index))
    adj = adj.reindex(close.index)
    close["GOLD_M"] = g
    adj["GOLD_M"] = g
    fx = close["KRW=X"].dropna() if krw else None
    assets = dict(ASSETS)
    local = ()
    if krw:
        # 2009년 이전 원화 현금 자료가 없어 그 기간만 미국 3개월 국채 이자로 대신한다.
        close["TBILL"], adj["TBILL"] = cash_idx, cash_idx
        assets[CASH] = ["153130.KS", "114260.KS", "TBILL"]
        # 국내 주식(EM 계좌): KODEX 200, 그 전은 EWY×환율
        rate = fx.reindex(close.index).ffill(limit=5)
        close["EWY_KRW"], adj["EWY_KRW"] = close["EWY"] * rate, adj["EWY"] * rate
        # Yahoo의 KODEX 200 자료는 2007-03~2009-03이 비어 있어서 2009-04부터만 쓴다.
        for frame in (close, adj):
            frame.loc[frame.index < "2009-04-01", "069500.KS"] = np.nan
        assets["KOSPI"] = ["069500.KS", "EWY_KRW"]
        assets["KTB10"] = "148070.KS"   # KOSEF 국고채10년 (2011-10~)
        assets["KTB3"] = "114260.KS"    # KODEX 국고채3년 (2009-07~)
        # 일반계좌 1 개별 종목·ETF (TIGER 코리아TOP10 상장 전은 KODEX 200으로 이어 붙임)
        kr = {"SAMSUNG": "005930.KS", "HYNIX": "000660.KS", "HYUNDAI": "005380.KS", "IBK": "024110.KS",
              "TOP10": ["292150.KS", "069500.KS", "EWY_KRW"]}
        for name, cols in kr.items():
            if all(c in close for c in ([cols] if isinstance(cols, str) else cols)):
                assets[name] = cols
        local = (CASH, "KOSPI", "KTB10", "KTB3", *kr)
    m = build_market(close, adj, assets, fx=fx, local=local)
    spx_t = _daily_total(close, adj, ["SPY", "VFINX"])
    ndx_t = _daily_total(close, adj, ["QQQ", "^NDX"])
    syn = {
        **({} if krw else {CASH: cash_idx}),
        # 2배 레버리지 합성(보수 연 0.9%, 차입 이자=현금 금리). 실제 ETF 상장 뒤에는 실제 값을 쓴다.
        "SSO": _splice_one(adj["SSO"], leveraged(spx_t, 2, .009, cash_d)),
        "QLD": _splice_one(adj["QLD"], leveraged(ndx_t, 2, .009, cash_d)),
        "UPRO": _splice_one(adj["UPRO"], leveraged(spx_t, 3, .009, cash_d)),
    }
    lev = build_market(pd.DataFrame(syn), pd.DataFrame(syn), {k: k for k in syn}, fx=fx)
    full = Market(
        close=m.close.join(lev.close), total=m.total.join(lev.total), high52=m.high52.join(lev.high52))
    if krw:
        usd = build_market(close, adj, {"SPX_USD": ASSETS["SPX"], "NDX_USD": ASSETS["NDX"]})
        full = Market(close=full.close.join(usd.close), total=full.total.join(usd.total),
                      high52=full.high52.join(usd.high52))
    full.extra["krw"] = close["KRW=X"].resample("ME").last()
    full.extra["close_d"], full.extra["adj_d"] = close, adj
    return full


def _blend(frame: pd.DataFrame, w: dict) -> pd.Series:
    r = sum(frame[k].pct_change(fill_method=None) * v for k, v in w.items())
    r = r[frame[list(w)].notna().all(axis=1)]
    return (1 + r.fillna(0)).cumprod() * 100


def _splice_one(main: pd.Series, older: pd.Series) -> pd.Series:
    main, older = main.dropna(), older.dropna()
    if main.empty:
        return older
    first = main.index[0]
    before = older[older.index <= first]
    if len(before) < 2:
        return main
    return pd.concat([before.iloc[:-1] * (main.iloc[0] / before.iloc[-1]), main])


def _daily_total(close, adj, cols):
    s = adj[cols[0]].dropna()
    for c in cols[1:]:
        s = _splice_one(s, adj[c])
    return s


# ---------------------------------------------------------------- 실행할 전략 목록

def current(spx: str = "SPX", ndx: str = "NDX") -> dict:
    """현재 전략 4개. SSO·ISA 신호는 달러 기준 SPY·QQQ(원화 계산에서는 SPX_USD·NDX_USD)."""
    return {
        "GSM (현재)": S.gsm(),
        "LAA 변형 (현재)": S.laa_variant(),
        "SSO 단계 (현재)": S.ladder("SSO", spx, .70, S.SSO_STEPS),
        "ISA 단계 (현재)": S.ladder("QLD", ndx, 0.0, S.ISA_STEPS),
    }


CURRENT = current()
KRW_START = "2010-01-31"   # 원화 현금(국내 단기채 ETF) 자료가 있는 시점

BENCH = {
    "S&P500 100%": S.hold({"SPX": 1}),
    "나스닥100 100%": S.hold({"NDX": 1}),
    "60/40 (S&P·10년채)": S.hold({"SPX": .6, "UST10": .4}),
    "6자산 고정 (LAA 필터 없음)": S.hold(S.LAA_TARGET, S.QUARTER_MONTHS),
    "영구 포트폴리오": S.hold({"SPX": .25, "TLT": .25, "GOLD": .25, CASH: .25}, (12,)),
    "SSO 70/현금 30 매월": S.hold({"SSO": .7, CASH: .3}),
}

KNOWN = {
    "올웨더 (달리오)": S.hold({"SPX": .30, "TLT": .40, "UST10": .15, "GOLD": .075, "DBC": .075}, (12,)),
    "골든 버터플라이": S.hold({"SPX": .2, "IWM": .2, "TLT": .2, "SHY": .2, "GOLD": .2}, (12,)),
    "GTAA 5 (파버)": S.gtaa(),
    "듀얼 모멘텀 GEM": S.dual_momentum(),
    "가속 듀얼 모멘텀 ADM": S.adm(),
    "VAA-G4": S.vaa(),
    "DAA-G12": S.daa(),
    "BAA-G12": S.baa(),
    "HAA": S.haa(),
    "원조 LAA (실업률 제외)": S.laa_original(),
}

VARIANTS = {
    # GSM
    "GSM 100% 투자": S.gsm(invest=1.0),
    "GSM 현금 대신 10년채": S.gsm(safe="UST10"),
    "GSM 상위 2개 분산": S.gsm(top=2),
    "GSM 13612W 모멘텀": S.gsm(mom="13612w"),
    "GSM +금·10년채 후보": S.gsm(cands=("NDX", "SPX", "WORLD", "EURO", "GOLD", "UST10")),
    "GSM +금 후보, 상위 2개": S.gsm(cands=("NDX", "SPX", "WORLD", "EURO", "GOLD", "UST10"), top=2),
    # LAA
    "LAA 매월 복원": S.laa_variant(restore=tuple(range(1, 13))),
    "LAA 분기 + 필터 회복 시 즉시 재매수": S.laa_variant(rebuy=True),
    "LAA 필터 4개 주식 모두": S.laa_variant(filters=("NDX", "EURO", "SPX", "WORLD")),
    "LAA 필터 몫을 10년채로": S.laa_variant(safe="UST10"),
    # SSO
    "SSO 단계 + SPY SMA 아래면 추가매수 보류": S.ladder("SSO", "SPX", .70, S.SSO_STEPS, sma_exit=True),
    "SSO 단계 -10/-20/-30": S.ladder("SSO", "SPX", .70, [(-.10, .80), (-.20, .90), (-.30, 1.0)]),
    "SSO 70/30 + SSO가 SMA 아래면 현금 100%": S.gsm(cands=("SSO",), invest=.7, safe=CASH, sma_n=10),
    # ISA
    "ISA 회복 기준 고점 -5%": S.ladder("QLD", "NDX", 0.0, S.ISA_STEPS, recover=-.05),
    "ISA 단계 -20/-30/-40": S.ladder("QLD", "NDX", 0.0, [(-.20, 1 / 3), (-.30, 2 / 3), (-.40, 1.0)]),
    "ISA 단계 + 나스닥 SMA 아래면 현금": S.ladder("QLD", "NDX", 0.0, S.ISA_STEPS, sma_sell=True),
    "ISA 단계 + 추가매수는 SMA 위에서만": S.ladder("QLD", "NDX", 0.0, S.ISA_STEPS, sma_exit=True),
    "ISA 단계 + 고점 -35%면 손절": S.ladder("QLD", "NDX", 0.0, S.ISA_STEPS, stop=-.35),
    "ISA 대신 GSM 방식(나스닥 2배)": S.gsm(cands=("QLD",), invest=1.0),
    "SSO 단계 + SPY SMA 아래면 70%로": S.ladder("SSO", "SPX", .70, S.SSO_STEPS, sma_sell=True),
}


# 보고서에서 제안 후보로 다시 보는 개선안
PICKS = ["GSM +금 후보, 상위 2개", "SSO 단계 + SPY SMA 아래면 추가매수 보류", "ISA 단계 + 나스닥 SMA 아래면 현금"]


def table(strats: dict, m: Market, start: str) -> tuple[pd.DataFrame, dict]:
    rows, results = [], {}
    cash_r = m.ret()[CASH]
    for name, fn in strats.items():
        res = run(fn, m, start, END)
        results[name] = res
        rows.append({"전략": name, **stats(res, cash_r)})
    return pd.DataFrame(rows).set_index("전략"), results


def crisis(results: dict) -> pd.DataFrame:
    periods = {
        "닷컴 2000-03~2002-09": ("2000-03", "2002-09"),
        "금융위기 2007-11~2009-02": ("2007-11", "2009-02"),
        "코로나 2020-02~03": ("2020-02", "2020-03"),
        "2022 긴축 2022-01~10": ("2022-01", "2022-10"),
        "2025-02~04 관세 충격": ("2025-02", "2025-04"),
    }
    out = {}
    for name, res in results.items():
        r = res["ret"]
        row = {}
        for p, (a, b) in periods.items():
            seg = r[(r.index >= pd.Timestamp(a)) & (r.index <= pd.Timestamp(b) + pd.offsets.MonthEnd(0))]
            row[p] = (1 + seg).prod() - 1 if len(seg) and seg.index[0] <= pd.Timestamp(a) + pd.offsets.MonthEnd(0) else np.nan
        out[name] = row
    return pd.DataFrame(out).T


PAIRS = {
    "133690.KS": ("TIGER 미국나스닥100", "QQQ"),
    "368590.KS": ("RISE 미국나스닥100", "QQQ"),
    "360750.KS": ("TIGER 미국S&P500", "SPY"),
    "379780.KS": ("RISE 미국S&P500", "SPY"),
    "251350.KS": ("KODEX MSCI선진국", "URTH"),
    "245350.KS": ("TIGER 유로스탁스배당30", "FDD"),
    "411060.KS": ("ACE KRX금현물", "GLD"),
    "308620.KS": ("KODEX 미국10년국채선물", "IEF"),
    "418660.KS": ("TIGER 미국나스닥100레버리지(합성)", "QLD"),
}


def tracking(m: Market) -> pd.DataFrame:
    """국내 ETF 월수익률과 (미국 ETF × 원/달러) 월수익률을 겹치는 기간에 비교한다."""
    close, adj = m.extra["close_d"], m.extra["adj_d"]
    fx = close["KRW=X"].resample("ME").last()
    rows = []
    for kr, (name, us) in PAIRS.items():
        if kr not in adj or us not in adj:
            continue
        a = adj[kr].resample("ME").last().pct_change(fill_method=None)
        b = (adj[us].resample("ME").last() * fx).pct_change(fill_method=None)
        both = pd.concat([a, b], axis=1).dropna()
        if len(both) < 12:
            continue
        ya, yb = len(both) / 12, len(both) / 12
        ca = (1 + both.iloc[:, 0]).prod() ** (1 / ya) - 1
        cb = (1 + both.iloc[:, 1]).prod() ** (1 / yb) - 1
        rows.append({
            "국내 ETF": f"{name} ({kr[:6]})", "대용치": f"{us}×환율", "기간": f"{both.index[0]:%Y-%m}~{both.index[-1]:%Y-%m}",
            "상관계수": round(both.corr().iloc[0, 1], 3), "국내 연수익": f"{ca * 100:.1f}%", "대용치 연수익": f"{cb * 100:.1f}%",
            "차이(연)": f"{(ca - cb) * 100:+.1f}%p",
        })
    return pd.DataFrame(rows).set_index("국내 ETF")


def fmt(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    pct = ["CAGR", "변동성", "MDD", "최악의 해", "최고의 해", "연 회전율"]
    for c in df.columns:
        if c in pct or "~" in c:
            df[c] = df[c].map(lambda v: "" if pd.isna(v) else f"{v * 100:.1f}%")
        elif c in ("샤프", "소르티노", "MAR"):
            df[c] = df[c].map(lambda v: "" if pd.isna(v) else f"{v:.2f}")
    return df


def main() -> None:
    OUT.mkdir(exist_ok=True)
    m = prepare()
    cols = ["CAGR", "변동성", "MDD", "샤프", "MAR", "최악의 해", "최장 회복(개월)", "연 회전율"]
    md = [f"# 백테스트 결과 (자동 생성: python -m backtest.run)\n\n끝: {END[:7]} · 미국 달러 기준 · 배당 포함 · 회전율당 0.1% 비용 · 세금 제외\n"]
    sections = [
        ("A. 장기(2000-01~): 현재 전략과 기본 비교", {**CURRENT, **BENCH}, LONG_START),
        ("B. 공통 기간(2007-03~): 잘 알려진 전략 포함", {**CURRENT, **{k: VARIANTS[k] for k in PICKS}, **BENCH, **KNOWN}, COMMON_START),
        ("C. 개선안 후보(2000-01~)", {**CURRENT, **VARIANTS}, LONG_START),
    ]
    all_res = {}
    for title, strats, start in sections:
        t, res = table(strats, m, start)
        all_res.update({f"{title[:1]}:{k}": v for k, v in res.items()})
        t.to_csv(OUT / f"{title[:1]}_stats.csv")
        md.append(f"## {title}\n\n{fmt(t[cols]).to_markdown()}\n")
        c = crisis(res)
        md.append(f"### 위기 구간 누적 수익률\n\n{fmt(c).to_markdown()}\n")
        if title.startswith("A"):
            y = pd.DataFrame({k: yearly(v) for k, v in res.items()})
            y.to_csv(OUT / "A_yearly.csv")
            md.append(f"### 연도별 수익률\n\n{y.map(lambda v: '' if pd.isna(v) else f'{v * 100:.1f}%').to_markdown()}\n")
    # D. 원화 기준(국내 상장 환노출 ETF로 투자한 것과 비슷)
    mk = prepare(krw=True)
    krw_strats = {
        **current("SPX_USD", "NDX_USD"),
        "S&P500 100%": BENCH["S&P500 100%"],
        "나스닥100 100%": BENCH["나스닥100 100%"],
        "6자산 고정 (LAA 필터 없음)": BENCH["6자산 고정 (LAA 필터 없음)"],
        "GSM +금 후보, 상위 2개": VARIANTS["GSM +금 후보, 상위 2개"],
        "LAA 필터 4개 주식 모두": VARIANTS["LAA 필터 4개 주식 모두"],
        "SSO 70/30 + SSO가 SMA 아래면 현금 100%": VARIANTS["SSO 70/30 + SSO가 SMA 아래면 현금 100%"],
        "SSO 단계 + SPY SMA 아래면 추가매수 보류": S.ladder("SSO", "SPX_USD", .70, S.SSO_STEPS, sma_exit=True),
        "ISA 단계 + 나스닥 SMA 아래면 현금": S.ladder("QLD", "NDX_USD", 0.0, S.ISA_STEPS, sma_sell=True),
        "HAA": KNOWN["HAA"],
        "BAA-G12": KNOWN["BAA-G12"],
    }
    t, res = table(krw_strats, mk, KRW_START)
    all_res.update({f"D:{k}": v for k, v in res.items()})
    t.to_csv(OUT / "D_stats.csv")
    md.append(f"## D. 원화 기준({KRW_START[:7]}~): 해외 자산은 원/달러 환산, 현금은 국내 단기채 ETF\n\n{fmt(t[cols]).to_markdown()}\n")
    md.append(f"### 위기 구간 누적 수익률\n\n{fmt(crisis(res)).to_markdown()}\n")
    md.append(f"## E. 국내 ETF와 미국 대용치(원화 환산) 비교\n\n{tracking(m).to_markdown()}\n")
    curves = pd.DataFrame({k: (1 + v["ret"]).cumprod() for k, v in all_res.items()})
    curves.to_csv(OUT / "curves.csv")
    (OUT / "summary.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
