"""판단하는 날짜를 바꾸면 결과가 얼마나 달라지나: python -m backtest.timing 비중.json

- 월말(0) 대신 그달 마지막 거래일보다 5·10·15거래일 앞선 날 종가로 판단하고 그날 매매한다고 본다.
- "두 번 나눠 판단": 돈을 반으로 나눠 반은 월말, 반은 10거래일 앞선 날 판단(각자 따로 불어남).
결과가 날짜에 따라 크게 흔들리면 월말이라는 날짜에 운이 섞인 것이다.
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from backtest import engine
from backtest import evaluate as E
from backtest.best_mix import seg_stats
from backtest.mix2 import _extend
from backtest.run import prepare
from backtest.stress import CHOSEN

OFFSETS = (0, 5, 10, 15)
LABEL = {0: "월말", 5: "월말 5거래일 전", 10: "월말 10거래일 전(월중)", 15: "월말 15거래일 전"}


def values(offset: int, w: dict) -> dict:
    engine.SAMPLE_OFFSET = offset
    base = {"krw": _extend(prepare(krw=True), True), "usd": _extend(prepare(krw=False), False)}
    tick = pd.read_csv("backtest/data/tickers.csv")
    avail = set(tick.loc[tick["rows"] > 0, "ticker"])
    dom, info = E.domestic_market(base["krw"], base["usd"], avail)
    ser = E.account_series({"krw": base["krw"], "usd": base["usd"], "dom": dom}, info, "기본")
    engine.SAMPLE_OFFSET = 0
    out = {}
    for name, c in CHOSEN.items():
        out[name] = {k: E.portfolio_paths(ser, c, w, k).sum(axis=1) for k in ("krw", "usd")}
    return out


def stats_of(v: pd.Series) -> tuple:
    r = v.pct_change()
    r.iloc[0] = v.iloc[0] - 1
    cg, md, wo = seg_stats(r.values[None, :])
    return cg[0], md[0], wo[0]


def main(path: str) -> None:
    acc = json.loads(open(path, encoding="utf-8").read())
    tot = sum(acc.values())
    w = {k: v / tot for k, v in acc.items()}
    V = {o: values(o, w) for o in OFFSETS}
    rows = []
    for name in CHOSEN:
        for o in OFFSETS:
            ck, mk, wk = stats_of(V[o][name]["krw"])
            cu, mu, _ = stats_of(V[o][name]["usd"])
            rows.append({"조합": name, "판단일": LABEL[o], "원화 연수익": ck, "원화 MDD": mk, "최악 12개월": wk,
                         "달러 연수익": cu, "달러 MDD": mu})
        mix = {k: (V[0][name][k] + V[10][name][k]) / 2 for k in ("krw", "usd")}
        ck, mk, wk = stats_of(mix["krw"])
        cu, mu, _ = stats_of(mix["usd"])
        rows.append({"조합": name, "판단일": "두 번 나눠(월말 반 + 월중 반)", "원화 연수익": ck, "원화 MDD": mk,
                     "최악 12개월": wk, "달러 연수익": cu, "달러 MDD": mu})
    t = pd.DataFrame(rows)
    spread = t[t["판단일"].isin(LABEL.values())].groupby("조합").agg(
        수익폭=("원화 연수익", lambda s: s.max() - s.min()), MDD폭=("원화 MDD", lambda s: s.max() - s.min()),
        달러MDD폭=("달러 MDD", lambda s: s.max() - s.min()))
    for c in ["원화 연수익", "원화 MDD", "최악 12개월", "달러 연수익", "달러 MDD"]:
        t[c] = t[c].map(lambda x: f"{x * 100:.1f}%")
    print(t.to_markdown(index=False))
    print("\n판단일 4가지 사이의 차이(최고 − 최저)\n")
    print(spread.map(lambda x: f"{x * 100:.1f}%p").to_markdown())


if __name__ == "__main__":
    main(*sys.argv[1:])
