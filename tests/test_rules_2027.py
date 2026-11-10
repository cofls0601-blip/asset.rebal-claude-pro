"""2027 규칙(DAA, ISA S&P2배 추세, 일반계좌 1 국내 절반 필터) — 정답을 손으로 계산할 수 있는 예제."""
import unittest
from datetime import date

import pandas as pd

from streamlit_app import rules as r

DAY = date(2026, 10, 30)
OFF = ['360750', '133690', '195970', '195980', '411060', '308620', '476760']


def monthly(values, day=DAY):
    """마지막 값이 day(이번 달 월말로 보는 기준일)인 월말 값들을 영업일마다 채운 시세."""
    day = pd.Timestamp(day)
    ends = pd.date_range(end=day + pd.offsets.MonthEnd(0), periods=len(values), freq='ME')
    ends = ends[:-1].append(pd.DatetimeIndex([day]))
    idx = pd.bdate_range(ends[0] - pd.Timedelta(days=25), day)
    s = pd.Series(index=idx, dtype=float)
    for e, v in zip(ends, values):
        s[(s.index <= e) & s.isna()] = v
    return s


def growth(m1, m3, m6, m12):
    """1·3·6·12개월 수익률이 정확히 주어진 값이 되는 13개 월말 값."""
    last = 100.
    v = [None] * 13
    v[-1] = last
    v[-2] = last / (1 + m1)
    v[-4] = last / (1 + m3)
    v[-7] = last / (1 + m6)
    v[0] = last / (1 + m12)
    for i in range(13):
        if v[i] is None:
            v[i] = v[i - 1]
    return v


def score(m1, m3, m6, m12):
    return 12 * m1 + 4 * m3 + 2 * m6 + m12


def daa_view(weights=None):
    rows = [(t, f'E{t}', '') for t in OFF] + [('153130', 'KODEX 단기채권', '현금'), ('CASH', '현금', '현금')]
    w = weights or {t: 100 / len(rows) for t, _, _ in rows}
    v = pd.DataFrame([dict(ticker=t, name=n, role=ro, close=1., sma10=None, return12=None, weight=w.get(t, 0.), target_pct=0.)
                      for t, n, ro in rows])
    v.insert(0, 'strategy', 'DAA')
    return v


def fetcher(table):
    def f(ticker, market, day, adjusted=False):
        return monthly(growth(*table[ticker]))
    return f


BASE = {  # 1·3·6·12개월 수익률
    '360750': (.02, .05, .08, .15), '133690': (.03, .06, .10, .20), '195970': (.01, .02, .03, .05),
    '195980': (.01, .01, .02, .04), '411060': (-.01, .02, .05, .10), '308620': (.00, .01, .01, .02),
    '476760': (-.02, -.03, -.02, -.05), '153130': (.003, .009, .018, .035), 'AGG': (.004, .01, .02, .03)}


class DAATests(unittest.TestCase):
    def test_scores_match_hand_calculation(self):
        sc, parts = r.momentum_13612(monthly(growth(.02, .05, .08, .15)), DAY)
        self.assertAlmostEqual(sc, score(.02, .05, .08, .15))
        self.assertAlmostEqual(parts[12], .15)

    def test_both_canaries_positive_full_offense_top3(self):
        d = r.check_daa(daa_view(), DAY, fetcher(BASE))
        # 점수: 133690 3.24, 360750 2.03, 411060 0.08+0.10+... → 계산해서 상위 3개
        ranked = sorted(OFF, key=lambda t: -score(*BASE[t]))
        top = ranked[:3]
        for t in OFF:
            self.assertAlmostEqual(d['targets'][t], 100 / 3 if t in top else 0)
        self.assertEqual(d['targets']['153130'], 0)
        self.assertEqual(d['targets']['CASH'], 0)
        self.assertIn('위험 신호 0개', d['headline'])

    def test_one_canary_negative_half_offense_rest_to_stronger_defense(self):
        t = dict(BASE, AGG=(-.01, -.02, -.01, -.01))
        d = r.check_daa(daa_view(), DAY, fetcher(t))
        top = sorted(OFF, key=lambda x: -score(*t[x]))[:3]
        safe = max(['308620', '153130'], key=lambda x: score(*t[x]))
        for x in top:
            self.assertAlmostEqual(d['targets'][x], 50 / 3 + (50 if x == safe else 0))
        self.assertAlmostEqual(d['targets'][safe], 50 + (50 / 3 if safe in top else 0))
        self.assertAlmostEqual(sum(d['targets'].values()), 100)
        self.assertIn('공격 50%', d['headline'])

    def test_both_canaries_negative_all_defense(self):
        t = dict(BASE, AGG=(-.01, -.02, -.01, -.01), **{'195980': (-.05, -.08, -.1, -.1)})
        t['308620'] = (-.01, -.02, -.03, -.04)  # 10년채가 단기채권보다 약함 → 단기채권
        d = r.check_daa(daa_view(), DAY, fetcher(t))
        self.assertEqual(d['targets']['153130'], 100)
        self.assertEqual(sum(v for k, v in d['targets'].items() if k != '153130'), 0)

    def test_missing_candidate_cannot_judge(self):
        v = daa_view()
        v = v[v.ticker != '476760']
        d = r.evaluate(v, DAY, fetcher(BASE))[0]
        self.assertEqual(d['status'], '계산 불가')
        self.assertIn('476760', d['headline'])

    def test_short_history_cannot_judge(self):
        def short(t, m, day, adjusted=False):
            return monthly([100] * 8)
        d = r.evaluate(daa_view(), DAY, short)[0]
        self.assertEqual(d['status'], '계산 불가')

    def test_uses_adjusted_prices_when_available(self):
        seen = []

        def f(t, m, day, adjusted=False):
            seen.append(adjusted)
            return monthly(growth(*BASE[t]))
        r.check_daa(daa_view(), DAY, f)
        self.assertTrue(all(seen))


def trend_prices(last):
    idx = pd.bdate_range(end=pd.Timestamp(DAY), periods=300)
    s = pd.Series(100., index=idx)
    s.iloc[-1] = last
    return lambda t, m, d: s


class ISATrend2027Tests(unittest.TestCase):
    def view(self, weight):
        rows = [('225040', 'TIGER 미국S&P500레버리지(합성 H)', '레버리지', weight), ('153130', 'KODEX 단기채권', '현금', 100 - weight),
                ('CASH', '현금', '현금', 0)]
        v = pd.DataFrame([dict(ticker=t, name=n, role=ro, close=1., sma10=None, return12=None, weight=w, target_pct=0.) for t, n, ro, w in rows])
        v.insert(0, 'strategy', 'ISA')
        return v

    def test_spy_signal_and_cash_ticker(self):
        p = dict(mode='trend', signal='SPY', cash='153130')
        up = r.check_trend('ISA', self.view(0), DAY, trend_prices(120), p)
        self.assertEqual(up['targets'], {'225040': 100., '153130': 0., 'CASH': 0.})
        down = r.check_trend('ISA', self.view(100), DAY, trend_prices(80), p)
        self.assertEqual(down['targets'], {'225040': 0., '153130': 100., 'CASH': 0.})
        self.assertIn('KODEX 단기채권 100%', down['headline'])


def kr_view(samsung, hynix, spy, cash):
    rows = [('005930', '삼성전자', samsung), ('000660', 'SK하이닉스', hynix), ('SPY', 'SPDR S&P 500 ETF', spy), ('CASH', '현금', cash)]
    v = pd.DataFrame([dict(ticker=t, name=n, role='', close=1., sma10=None, return12=None, weight=w, target_pct=0.) for t, n, w in rows])
    v.insert(0, 'strategy', 'EM')
    return v


def kodex(prev_above, now_above):
    """11개 월말: 지난달과 이번 달이 10개월 평균 위/아래가 되게."""
    vals = [100.] * 9 + [130. if prev_above else 70., 130. if now_above else 60.]
    return lambda t, m, d: monthly(vals, d)


class KrHalfTests(unittest.TestCase):
    P = dict(mode='kr_half', kr_share=50, signal='069500', spx='SPY', month=12, max_pct=30, start='2027-01')

    def test_no_change_without_flip(self):
        d = r.check_kr_half('EM', kr_view(30, 25, 40, 5), DAY, kodex(True, True), self.P)
        self.assertFalse(d['changed'])
        self.assertIn('할 일 없음', d['headline'])

    def test_flip_below_halves_korean_share_keeping_ratio(self):
        d = r.check_kr_half('EM', kr_view(30, 30, 40, 0), DAY, kodex(True, False), self.P)
        self.assertEqual(d['targets'], {'005930': 12.5, '000660': 12.5, 'SPY': 50., 'CASH': 25.})

    def test_flip_above_restores_full_korean_share(self):
        d = r.check_kr_half('EM', kr_view(15, 10, 50, 25), DAY, kodex(False, True), self.P)
        self.assertAlmostEqual(d['targets']['005930'], 30.)
        self.assertAlmostEqual(d['targets']['000660'], 20.)
        self.assertAlmostEqual(d['targets']['SPY'], 50.)
        self.assertAlmostEqual(d['targets']['CASH'], 0.)

    def test_december_rebalances_and_caps_single_stock(self):
        d = r.check_kr_half('EM', kr_view(45, 5, 45, 5), date(2026, 12, 30), kodex(True, True), self.P)
        # 국내 몫 50% 중 삼성 45/50 → 45%지만 상한은 국내 몫의 30% = 15%
        self.assertAlmostEqual(d['targets']['005930'], 15.)
        self.assertAlmostEqual(d['targets']['000660'], 5.)
        self.assertAlmostEqual(d['targets']['SPY'], 50.)
        self.assertAlmostEqual(d['targets']['CASH'], 30.)
        self.assertIn('삼성전자', d['headline'])

    def test_start_month_sets_ratio(self):
        d = r.check_kr_half('EM', kr_view(60, 40, 0, 0), date(2027, 1, 29), kodex(True, True), self.P)
        self.assertEqual(d['targets'], {'005930': 30., '000660': 20., 'SPY': 50., 'CASH': 0.})

    def test_evaluate_dispatches_kr_half(self):
        import json
        st = pd.DataFrame([dict(code='EM', params_json=json.dumps(self.P))])
        d = r.evaluate(kr_view(30, 30, 40, 0), DAY, kodex(True, False), st)[0]
        self.assertEqual(d['status'], '판정')


if __name__ == '__main__':
    unittest.main()
