"""시대별 변동성과 하락·회복 속도: python -m backtest.vol_history

- 변동성: 일간 수익률 표준편차 × √252 (가격 지수, 배당 제외). 시대별 평균과 최근(2020~) 비교.
- 하락 사건: 고점 대비 -10% 이상(조정), -20% 이상(약세장)인 사건마다
  고점→바닥 거래일, 바닥→전고점 회복 거래일, 바닥→바닥 대비 +20% 반등 거래일.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.engine import DATA_DIR

ERAS = [("1928-1949", "1928", "1949"), ("1950-1969", "1950", "1969"), ("1970-1989", "1970", "1989"),
        ("1990-1999", "1990", "1999"), ("2000-2009", "2000", "2009"), ("2010-2019", "2010", "2019"),
        ("2020-2026", "2020", "2026")]


def load():
    c = pd.read_csv(DATA_DIR / "close_daily.csv.gz", index_col=0, parse_dates=True)
    fx = c["KRW=X"]
    kr = c["069500.KS"].copy()
    kr[kr.index < "2009-04-01"] = np.nan  # 자료 빈 구간
    ewy = (c["EWY"] * fx).dropna()
    # KODEX 200을 EWY×환율로 이어 붙인 원화 한국 주식
    k = kr.dropna()
    before = ewy[ewy.index < k.index[0]]
    korea = pd.concat([before * (k.iloc[0] / before.iloc[-1]), k])
    return {"S&P500 (1928~)": c["^GSPC"].dropna(), "나스닥 종합 (1971~)": c["^IXIC"].dropna(),
            "한국 주식 원화 (2000~)": korea}


def vol_table(s: pd.Series) -> pd.DataFrame:
    r = s.pct_change().dropna()
    rows = {}
    for name, a, b in ERAS:
        rr = r.loc[a:b]
        if len(rr) < 250:
            continue
        yrs = len(rr) / 252
        rows[name] = {"연 변동성": rr.std() * np.sqrt(252),
                      "1년 변동성 중간값": rr.rolling(252).std().dropna().median() * np.sqrt(252) if len(rr) > 300 else np.nan,
                      "±2% 넘는 날/년": (rr.abs() > .02).sum() / yrs, "±4% 넘는 날/년": (rr.abs() > .04).sum() / yrs}
    return pd.DataFrame(rows).T


def episodes(s: pd.Series, depth: float) -> pd.DataFrame:
    """고점 대비 depth 이상 빠진 사건. 회복 = 전고점 회복."""
    s = s.dropna()
    peak_val, peak_i = s.iloc[0], 0
    out = []
    i, n = 0, len(s)
    v = s.values
    while i < n:
        if v[i] >= peak_val:
            peak_val, peak_i = v[i], i
            i += 1
            continue
        if v[i] / peak_val - 1 <= -depth:
            # 바닥 찾기: 전고점 회복 전까지의 최저
            j = i
            trough_i = i
            while j < n and v[j] < peak_val:
                if v[j] < v[trough_i]:
                    trough_i = j
                j += 1
            rec = j if j < n else None
            reb = next((t for t in range(trough_i, n) if v[t] >= v[trough_i] * 1.2), None)
            out.append({"고점": s.index[peak_i].date(), "바닥": s.index[trough_i].date(),
                        "하락폭": v[trough_i] / peak_val - 1, "고점→바닥(거래일)": trough_i - peak_i,
                        "바닥→+20% 반등(거래일)": (reb - trough_i) if reb is not None else np.nan,
                        "바닥→전고점 회복(거래일)": (rec - trough_i) if rec is not None else np.nan,
                        "회복": "예" if rec is not None else "아직"})
            if rec is None:
                break
            peak_val, peak_i = v[rec], rec
            i = rec + 1
            continue
        i += 1
    return pd.DataFrame(out)


def era_of(d) -> str:
    y = pd.Timestamp(d).year
    for name, a, b in ERAS:
        if int(a) <= y <= int(b):
            return name
    return ""


def main() -> None:
    data = load()
    for name, s in data.items():
        print(f"\n## {name}\n")
        t = vol_table(s)
        r = s.pct_change().dropna()
        recent = r.loc["2020":]
        long = r.loc[:"2019"]
        long50 = r.loc["1950":"2019"]
        print(t.map(lambda x: f"{x * 100:.1f}%" if x < 1 else f"{x:.1f}").to_markdown())
        print(f"\n최근(2020~) 연 변동성 {recent.std() * np.sqrt(252) * 100:.1f}% vs 2019년까지 전체 {long.std() * np.sqrt(252) * 100:.1f}%"
              f" (1950~2019 {long50.std() * np.sqrt(252) * 100:.1f}%, 2010~2019 {r.loc['2010':'2019'].std() * np.sqrt(252) * 100:.1f}%)")
        for depth in (.10, .20):
            e = episodes(s, depth)
            if e.empty:
                continue
            e["시대"] = e["고점"].map(era_of)
            g = e.groupby("시대").agg(횟수=("하락폭", "size"), 평균하락=("하락폭", "mean"),
                                    하락기간=("고점→바닥(거래일)", "median"), 반등20=("바닥→+20% 반등(거래일)", "median"),
                                    회복기간=("바닥→전고점 회복(거래일)", "median"))
            g = g.reindex([x for x, _, _ in ERAS if x in g.index])
            g["평균하락"] = g["평균하락"].map(lambda x: f"{x * 100:.0f}%")
            print(f"\n### 고점 대비 -{depth * 100:.0f}% 이상 하락 (시대별 중간값, 거래일)\n")
            print(g.rename(columns={"하락기간": "고점→바닥", "반등20": "바닥→+20% 반등", "회복기간": "바닥→전고점 회복"})
                  .to_markdown())
            if depth == .20:
                show = e[e["고점"] >= pd.Timestamp("1987-01-01").date()].copy()
                show["하락폭"] = show["하락폭"].map(lambda x: f"{x * 100:.0f}%")
                print("\n1987년 이후 -20% 사건\n")
                print(show.drop(columns=["시대"]).to_markdown(index=False))


if __name__ == "__main__":
    main()
