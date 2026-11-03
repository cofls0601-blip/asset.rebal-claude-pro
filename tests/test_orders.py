import unittest
import pandas as pd
from streamlit_app.orders import plan_orders


def account(rows):
    """rows: (ticker, market, close, fx, shares); CASH rows use close=1."""
    v=pd.DataFrame([dict(ticker=t,name='N'+t,market=m,close=c,fx=f,shares=s) for t,m,c,f,s in rows])
    v['value']=v.close*v.fx*v.shares;return v


class OrderTests(unittest.TestCase):
    def test_sell_first_then_buy_with_proceeds(self):
        v=account([('A','KR',100,1,100),('B','KR',50,1,0),('CASH','KR',1,1,0)])  # total 10,000
        orders,notes=plan_orders(v,{'A':0,'B':80,'CASH':20})
        self.assertEqual([(o['side'],o['ticker'],o['shares']) for o in orders],[('매도','A',100),('매수','B',160)])
        self.assertEqual(notes,[])

    def test_buys_are_cut_when_cash_is_short(self):
        # Selling whole shares of A raises 560, so with 300 cash only 8 of the 9 B shares fit.
        v=account([('A','KR',70,1,10),('B','KR',100,1,0),('CASH','KR',1,1,300)])
        orders,notes=plan_orders(v,{'A':10,'B':90,'CASH':0})
        self.assertEqual([(o['side'],o['ticker'],o['shares']) for o in orders],[('매도','A',8),('매수','B',8)])
        self.assertEqual(notes,['NB: 현금 부족으로 1주 줄임'])

    def test_whole_shares_and_us_fractions(self):
        v=account([('QQQ','US',100,1500,0),('CASH','KR',1,1,1_000_000)])
        whole,_=plan_orders(v,{'QQQ':100,'CASH':0})
        self.assertEqual(whole[0]['shares'],6)  # 150,000원 per share
        frac,_=plan_orders(v,{'QQQ':100,'CASH':0},fractional_us=True)
        self.assertAlmostEqual(frac[0]['shares'],6.6666,places=4)

    def test_zero_target_sells_everything_and_tiny_gaps_are_ignored(self):
        v=account([('A','KR',100,1,7),('CASH','KR',1,1,30)])  # A 700 / 730
        orders,_=plan_orders(v,{'A':0,'CASH':100})
        self.assertEqual(orders[0]['shares'],7)
        none,_=plan_orders(v,{'A':700/730*100+1,'CASH':30/730*100-1})  # gap of 7.3원 < half a share
        self.assertEqual(none,[])


if __name__=='__main__':unittest.main()
