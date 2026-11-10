"""월말 판정 리허설: python -m backtest.rehearsal 2026-11-30

2027 템플릿을 빈 원장에 적용하고, 저장소의 공개 시세(backtest/data)로 **앱과 같은 판정 함수**
(streamlit_app.rules.evaluate)를 돌린다. Streamlit Cloud 앱이 실시간 시세로 낸 판정과 비교해
시세 불러오기 문제를 찾는 용도다. 보유 수량은 가짜(각 1주)라 주문 수량은 의미가 없고 판정만 본다.
일반계좌 1의 국내 주식은 KODEX 200 한 종목으로 대신한다.
"""
from __future__ import annotations

import sys
from datetime import date

import pandas as pd

from backtest.engine import DATA_DIR
from streamlit_app import manual as m
from streamlit_app import rules
from streamlit_app.ledger import empty_workspace
from streamlit_app.template import apply_template, load_template


def fetcher():
    close = pd.read_csv(DATA_DIR / "close_daily.csv.gz", index_col=0, parse_dates=True)
    adj = pd.read_csv(DATA_DIR / "adjclose_daily.csv.gz", index_col=0, parse_dates=True)

    def fetch(ticker, market, day, adjusted=False):
        col = f"{ticker}.KS" if market == "KR" and ticker[:6].isdigit() else ticker
        frame = adj if adjusted else close
        if col not in frame:
            return pd.Series(dtype=float)
        s = frame[col].dropna()
        return s[s.index <= pd.Timestamp(day)]
    return fetch


def main(day_text: str) -> None:
    day = date.fromisoformat(day_text)
    w = empty_workspace()
    h, s, _, _ = apply_template(w["holdings"], w["strategies"], w["strategy_versions"], load_template())
    kr = pd.DataFrame([dict(strategy="EM", account="일반계좌 1", ticker="069500", name="KODEX 200 (국내 주식 대신)",
                            market="KR", category="신흥국 주식", role="", target_pct=0., shares=1.)])
    h = pd.concat([h, kr], ignore_index=True)
    h["shares"] = h.ticker.map(lambda t: 1000. if t == "CASH" else 1.)
    h = m.validate_holdings(h)
    fetch = fetcher()
    view, errors = m.valuation(h, day, fetch)
    for e in errors:
        print("시세 오류:", e)
    print(f"# {day} 판정 (저장소 시세, 앱과 같은 판정 함수)\n")
    for d in rules.evaluate(view, day, fetch, s):
        if d["status"] == "판정 없음":
            continue
        acct = view.loc[view.strategy.eq(d["code"]), "account"].iloc[0]
        print(f"## {acct} ({d['code']}) — {d['status']}\n\n{d['headline']}\n")
        if d["evidence"]:
            print(pd.DataFrame(d["evidence"]).to_markdown(index=False))
        if d.get("targets"):
            t = {k: round(v, 1) for k, v in d["targets"].items() if v > 0.05}
            print(f"\n목표 비중: {t}\n")


if __name__ == "__main__":
    main(*sys.argv[1:])
