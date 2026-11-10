"""앱 판정(streamlit_app.rules)과 백테스트 판정(backtest)이 같은 시세에서 매달 똑같은지 확인한다.

같은 규칙을 두 번 구현했으므로, 둘이 어긋나면 어느 한쪽이 틀린 것이다.
시세는 저장소의 backtest/data(공개 시세)를 쓴다. 국내 ETF 상장 전 기간은 백테스트와 같은 대용치다.
"""
import unittest

import pandas as pd

from backtest import evaluate as E
from backtest import strategies as S
from backtest.engine import CASH, run
from backtest.run import END, prepare
from streamlit_app import rules as r

TICKER = {"SPX": "360750", "NDX": "133690", "EFA": "195970", "EEM": "195980", "GOLD": "411060",
          "UST10": "308620", "TLT": "476760", CASH: "153130"}
NAME = {v: k for k, v in TICKER.items()}


class Markets:
    cache = None

    @classmethod
    def get(cls):
        if cls.cache is None:
            krw, usd = prepare(krw=True), prepare(krw=False)
            tick = pd.read_csv("backtest/data/tickers.csv")
            dom, _ = E.domestic_market(krw, usd, set(tick.loc[tick["rows"] > 0, "ticker"]))
            cls.cache = krw, usd, dom
        return cls.cache


def decided(res: pd.DataFrame) -> dict:
    """run() 결과의 비중은 다음 달 줄에 적혀 있다 → {판정한 월말: 비중}."""
    idx = list(res.index)
    return {idx[i - 1]: res["weights"].iloc[i] for i in range(1, len(idx))}


class DAAMatchesBacktest(unittest.TestCase):
    def test_every_month_same_targets(self):
        krw, usd, dom = Markets.get()
        res = run(E.P["DAA"][2](E.VARIANTS["기본"]), dom, "2005-01-31", END)
        want = decided(res)

        def fetch(ticker, market, day, adjusted=False):
            col = "AGG" if ticker == "AGG" else NAME[ticker]
            frame = usd.total if ticker == "AGG" else dom.total
            return frame[col].dropna()

        holdings = list(TICKER.values()) + ["CASH"]
        view = pd.DataFrame([dict(strategy="DAA", ticker=t, name=t, role="", close=1., sma10=None, return12=None,
                                  weight=100 / len(holdings), target_pct=0.) for t in holdings])
        months = [d for d in want if d >= pd.Timestamp("2006-01-31")]
        self.assertGreater(len(months), 200)
        for d in months:
            got = r.check_daa(view, d.date(), fetch)["targets"]
            exp = {TICKER[k]: v * 100 for k, v in want[d].items()}
            for t in holdings:
                with self.subTest(month=str(d.date()), ticker=t):
                    self.assertAlmostEqual(got.get(t, 0.), exp.get(t, 0.), places=6)


class KrHalfMatchesBacktest(unittest.TestCase):
    def test_trade_months_and_targets_match(self):
        krw, _, _ = Markets.get()
        start = pd.Timestamp("2006-01-31")
        res = run(S.kr_half_spx(.5), krw, str(start.date()), END)
        want = decided(res)
        traded = {d for d, w in want.items()}  # run이 비중을 정한 달(None이면 이전 비중 유지라 그대로 기록됨)
        # run()은 None이면 흘러간 비중을 적으므로, 실제 매매한 달은 전략을 직접 다시 돌려 찾는다.
        strat = S.kr_half_spx(.5)
        from backtest.engine import Context
        state, trades = {}, {}
        idx = krw.close.index
        for i, d in enumerate(idx):
            if d < start or d > pd.Timestamp(END):
                continue
            out = strat(d, Context(krw, i, {}, state))
            if out is not None:
                trades[d] = out
        self.assertTrue(traded)
        signal = krw.close["KOSPI"].dropna()
        P = dict(mode="kr_half", kr_share=50, signal="069500", spx="SPY", month=12, max_pct=100, start=f"{start:%Y-%m}")

        def fetch(ticker, market, day):
            return signal

        view = pd.DataFrame([dict(strategy="EM", ticker=t, name=t, role="", close=1., sma10=None, return12=None, weight=w, target_pct=0.)
                             for t, w in (("KOSPI", 40.), ("SPY", 40.), ("CASH", 20.))])
        months = [d for d in idx if start <= d <= pd.Timestamp(END) and d >= signal.index[10]]
        for d in months:
            got = r.check_kr_half("EM", view, d.date(), fetch, P)
            with self.subTest(month=str(d.date())):
                if d in trades:
                    exp = {"KOSPI": trades[d]["KOSPI"] * 100, "SPY": trades[d]["SPX"] * 100, "CASH": trades[d][CASH] * 100}
                    for t, v in exp.items():
                        self.assertAlmostEqual(got["targets"][t], v, places=6)
                else:
                    self.assertFalse(got["changed"])


if __name__ == "__main__":
    unittest.main()
