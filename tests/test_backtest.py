import unittest

import numpy as np
import pandas as pd

from backtest import strategies as S
from backtest.engine import CASH, Context, Market, run, stats


def market(prices: dict, high=None) -> Market:
    idx = pd.date_range("2000-01-31", periods=len(next(iter(prices.values()))), freq="ME")
    close = pd.DataFrame(prices, index=idx, dtype=float)
    if CASH not in close:
        close[CASH] = 100.0
    high52 = close.rolling(12, min_periods=1).max() if high is None else pd.DataFrame(high, index=idx)
    return Market(close=close, total=close.copy(), high52=high52)


class EngineTests(unittest.TestCase):
    def test_buy_and_hold_matches_price(self):
        m = market({"A": [100, 110, 121, 133.1]})
        res = run(S.hold({"A": 1}), m, "2000-01-31")
        self.assertAlmostEqual((1 + res.ret).prod(), 1.331)

    def test_drift_is_kept_when_strategy_returns_none(self):
        m = market({"A": [100, 200, 200], "B": [100, 100, 100]})
        res = run(S.hold({"A": .5, "B": .5}, months=(7,)), m, "2000-01-31")
        # 2월에 A가 두 배 → 비중 2/3, 3월에는 복원하지 않으므로 거래 없음
        self.assertEqual(res.turnover.iloc[1], 0)
        self.assertAlmostEqual(res.ret.iloc[0], .5)

    def test_cost_charged_on_turnover(self):
        m = market({"A": [100] * 4, "B": [100] * 4})
        flip = iter([{"A": 1}, {"B": 1}, {"A": 1}])
        res = run(lambda d, c: next(flip), m, "2000-01-31", cost=.01)
        self.assertAlmostEqual(res.ret.iloc[1], -.02)

    def test_stats_mdd(self):
        res = pd.DataFrame({"ret": [.1, -.5, .2], "turnover": [0, 0, 0]},
                           index=pd.date_range("2000-01-31", periods=3, freq="ME"))
        self.assertAlmostEqual(stats(res)["MDD"], -.5)


class StrategyTests(unittest.TestCase):
    def test_gsm_picks_best_above_sma_and_keeps_20_cash(self):
        up = list(np.linspace(100, 150, 13))
        flat_up = list(np.linspace(100, 120, 13))
        down = list(np.linspace(150, 100, 13))
        m = market({"NDX": up, "SPX": flat_up, "WORLD": down, "EURO": down})
        w = S.gsm()(m.close.index[-1], ctx(m, 12))
        self.assertEqual(set(w), {"NDX", CASH})
        self.assertAlmostEqual(w["NDX"], .8)
        self.assertAlmostEqual(w[CASH], .2)

    def test_gsm_all_below_sma_goes_cash(self):
        down = list(np.linspace(150, 100, 13))
        m = market({"NDX": down, "SPX": down, "WORLD": down, "EURO": down})
        self.assertEqual(S.gsm()(m.close.index[-1], ctx(m, 12)), {CASH: 1.0})

    def test_laa_moves_only_filtered_sleeve_to_cash_between_quarters(self):
        down = list(np.linspace(150, 100, 13))
        up = list(np.linspace(100, 150, 13))
        m = market({"NDX": down, "EURO": up, "SPX": up, "WORLD": up, "GOLD": up, "UST10": up})
        weights = dict(S.LAA_TARGET)
        weights[CASH] = 0.0
        c = ctx(m, 11, weights, {"started": True})  # 2000-12 → 분기 말
        w = S.laa_variant()(m.close.index[11], c)
        self.assertAlmostEqual(w["NDX"], 0)
        self.assertAlmostEqual(w[CASH], .125)
        c = ctx(m, 12, weights, {"started": True})  # 2001-01 → 분기 중간, 흘러간 비중 유지
        w = S.laa_variant()(m.close.index[12], c)
        self.assertAlmostEqual(w["GOLD"], .25)
        self.assertAlmostEqual(w[CASH], .125)

    def test_ladder_steps_like_rules(self):
        prices = [100] * 12 + [89, 84, 79, 100]
        m = market({"QQQ": prices, "LEV": prices})
        strat = S.ladder("LEV", "QQQ", 0.0, S.ISA_STEPS)
        state = {"started": True}
        self.assertAlmostEqual(strat(None, ctx(m, 12, {CASH: 1}, state))["LEV"], 1 / 3)
        # 이미 1단계 비중(허용폭 5%p 안)이면 같은 단계에서 다시 사지 않는다
        self.assertIsNone(strat(None, ctx(m, 12, {"LEV": .31, CASH: .69}, state)))
        self.assertAlmostEqual(strat(None, ctx(m, 13, {"LEV": .31, CASH: .69}, state))["LEV"], 2 / 3)
        self.assertAlmostEqual(strat(None, ctx(m, 14, {"LEV": .6, CASH: .4}, state))["LEV"], 1.0)
        self.assertAlmostEqual(strat(None, ctx(m, 15, {"LEV": 1.0}, state))["LEV"], 0.0)

    def test_ladder_stop_returns_to_base(self):
        prices = [100] * 12 + [60]
        m = market({"QQQ": prices, "LEV": prices})
        w = S.ladder("LEV", "QQQ", 0.0, S.ISA_STEPS, stop=-.35)(None, ctx(m, 12, {"LEV": 1.0}, {"started": True}))
        self.assertAlmostEqual(w["LEV"], 0.0)


class MomentumMixTests(unittest.TestCase):
    def test_relative_momentum_picks_stronger_or_cash(self):
        up = list(np.linspace(100, 130, 13))
        less = list(np.linspace(100, 110, 13))
        m = market({"KOSPI": up, "SPX": less})
        self.assertEqual(S.relative_momentum()(None, ctx(m, 12)), {"KOSPI": 1.0})
        down = list(np.linspace(130, 100, 13))
        m = market({"KOSPI": down, "SPX": down})
        self.assertEqual(S.relative_momentum()(None, ctx(m, 12)), {CASH: 1.0})

    def test_mix_halves_stocks_below_sma(self):
        down = list(np.linspace(150, 100, 13))
        m = market({"KOSPI": down, "A": down})
        w = S.mix({"A": 1, "KOSPI": 1}, .8, "KOSPI", .5)(m.close.index[12], ctx(m, 12))
        self.assertAlmostEqual(w["A"], .2)
        self.assertAlmostEqual(w[CASH], .6)


class TaxTests(unittest.TestCase):
    def test_korean_equity_is_not_taxed_but_us_etf_is(self):
        from backtest.optimize import after_tax
        idx = pd.date_range("2000-01-31", periods=12, freq="ME")
        base = {"ret": [.01] * 12, "turnover": [1.0] + [0.0] * 11}
        kr = after_tax(pd.DataFrame({**base, "weights": [{"KOSPI": 1.0}] * 12}, index=idx))
        us = after_tax(pd.DataFrame({**base, "weights": [{"SPX": 1.0}] * 12}, index=idx))
        self.assertAlmostEqual((1 + kr).prod(), 1.01 ** 12)
        gain = 1.01 ** 12 - 1
        self.assertAlmostEqual((1 + us).prod(), (1 + gain) * (1 - .22 * gain))


class PortfolioTests(unittest.TestCase):
    def test_combine_lets_each_account_grow_separately(self):
        from backtest.portfolio import combine
        idx = pd.date_range("2000-01-31", periods=2, freq="ME")
        res = {"A": pd.DataFrame({"ret": [1.0, 0.0]}, index=idx), "B": pd.DataFrame({"ret": [0.0, 0.0]}, index=idx)}
        port, share = combine(res, {"A": 50, "B": 50})
        self.assertAlmostEqual(port.ret.iloc[0], .5)
        self.assertAlmostEqual(share["A"].iloc[-1], 2 / 3)


def ctx(m, i, weights=None, state=None):
    return Context(m, i, weights or {CASH: 1.0}, state if state is not None else {})


if __name__ == "__main__":
    unittest.main()
