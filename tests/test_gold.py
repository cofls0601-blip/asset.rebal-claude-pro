import unittest
from datetime import date
import pandas as pd
from streamlit_app import manual as m


def fetch(t,market,day):
    idx=pd.to_datetime(['2026-10-26','2026-10-27'])
    prices={'GC=F':[3110.35,3421.385],'KRW=X':[1400.,1500.]}
    if t not in prices:raise AssertionError('unexpected symbol '+t)  # must never query Yahoo "GOLD_G"
    return pd.Series(prices[t],index=idx)


class GoldTests(unittest.TestCase):
    def holdings(self):
        h=pd.DataFrame([dict(strategy='금',account='금 현물',ticker='CASH',name='현금',market='KR',category='현금',role='',target_pct=0,shares=0)])
        return m.add_asset(h,'금',m.GOLD_ASSET,shares=37.5)

    def test_gold_row_defaults(self):
        r=self.holdings().iloc[-1]
        self.assertEqual((r.ticker,r.market,r.category,r.shares),('GOLD_G','US','금',37.5))

    def test_gram_value_from_international_price(self):
        v,e=m.valuation(self.holdings(),date(2026,10,27),fetch);self.assertFalse(e)
        g=v[v.ticker.eq('GOLD_G')].iloc[0]
        self.assertAlmostEqual(g.close,110.);self.assertAlmostEqual(g.value,37.5*110*1500)
        self.assertAlmostEqual(g.prev_value,37.5*100*1400)

    def test_fixed_categories(self):
        self.assertEqual(m.CATEGORIES,['현금','선진국 주식','선진국 채권','신흥국 주식','신흥국 채권','금'])


if __name__=='__main__':unittest.main()
