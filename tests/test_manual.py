import unittest
from datetime import date
import pandas as pd
from streamlit_app import manual as m
from streamlit_app.data import DataError, load_default_holdings, load_default_strategies, normalize_strategies
from streamlit_app.ledger import empty_workspace, backup_bytes, restore_backup
DAY=date(2026,9,30)
def ws():
 w=empty_workspace();w['holdings']=load_default_holdings();w['strategies']=normalize_strategies(load_default_strategies());return w
def fetch(t,market,day):
 if t=='KRW=X':return pd.Series([1300.],index=[pd.Timestamp(day)])
 return pd.Series(range(100,114),index=pd.date_range('2025-08-31',periods=14,freq='ME'))
class PortfolioTests(unittest.TestCase):
 def test_strategy_lifecycle_history(self):
  w=ws();w['snapshots']=pd.DataFrame([{'strategy':'NEW'}]);w=m.add_strategy(w,'NEW','연금','설명');w=m.change_strategy(w,'NEW','RENAMED','ISA','수정')
  self.assertEqual(w['holdings'].iloc[-1].account,'ISA');self.assertEqual(w['snapshots'].strategy.iloc[0],'NEW');w=m.delete_strategy(w,'RENAMED');self.assertNotIn('RENAMED',w['strategies'].code.tolist())
 def test_strategy_validation(self):
  for c,a in [('DEMO','a'),('','a'),('x','')]:
   with self.assertRaises(DataError):m.add_strategy(ws(),c,a)
  w=m.add_strategy(ws(),'x','a')
  with self.assertRaises(DataError):m.change_strategy(w,'x','DEMO','a','')
 def test_asset_lifecycle(self):
  h=m.add_asset(ws()['holdings'],'DEMO',{'ticker':'069500','name':'KODEX 200','market':'KR'},0,10);self.assertEqual(h.iloc[-1].ticker,'069500')
  with self.assertRaises(DataError):m.add_asset(h,'DEMO',{'ticker':'69500','market':'KR'})
  h=m.delete_asset(h,'DEMO','069500');self.assertNotIn('069500',h.ticker.tolist())
  with self.assertRaises(DataError):m.delete_asset(h,'DEMO','CASH')
 def test_held_deletion(self):
  w=ws();w['holdings'].loc[0,'shares']=10
  with self.assertRaises(DataError):m.delete_asset(w['holdings'],'DEMO','360750')
  with self.assertRaises(DataError):m.delete_strategy(w,'DEMO')
 def test_quantity_target_validation(self):
  for q,t in [(-1,0),(float('nan'),0),(.5,0),(0,101),(0,-1),(0,float('inf'))]:
   with self.assertRaises(DataError):m.add_asset(ws()['holdings'],'DEMO',{'ticker':'069500','market':'KR'},q,t)
  h=m.add_asset(ws()['holdings'],'DEMO',{'ticker':'QQQ','market':'US'},.5,25);self.assertEqual(h.iloc[-1].shares,.5)
 def test_buy_sell(self):
  h,b,a=m.adjust(ws()['holdings'],'DEMO','360750',10,'매수');self.assertEqual(a,10);h,b,a=m.adjust(h,'DEMO','360750',3,'매도');self.assertEqual(a,7)
  for q in [8,0,-1,float('nan')]:
   with self.assertRaises(DataError):m.adjust(h,'DEMO','360750',q,'매도')
 def test_valuation_fx_indicators(self):
  h=m.add_asset(ws()['holdings'],'DEMO',{'ticker':'QQQ','market':'US'},2,0);v,e=m.valuation(h,DAY,fetch);self.assertFalse(e);self.assertEqual(v.iloc[-1].value,113*2*1300);self.assertEqual(v.iloc[-1].sma10,108.5);self.assertAlmostEqual(v.weight.sum(),100)
 def test_bad_prices(self):
  for day in ['2026-10-01','2026-08-01']:
   v,e=m.valuation(ws()['holdings'],DAY,lambda t,m,d:pd.Series([1.],index=[pd.Timestamp(day)]));self.assertTrue(e);self.assertTrue(v.weight.isna().all())
 def test_midmonth(self):
  d=date(2026,9,15)
  def daily(t,market,day):return pd.concat([fetch(t,market,DAY),pd.Series([999.],index=[pd.Timestamp(d)])])
  v,e=m.valuation(ws()['holdings'],d,daily);self.assertFalse(e);self.assertEqual(v.sma10.iloc[0],107.5)
 def test_backup(self):
  w=ws();w['holdings']=m.add_asset(w['holdings'],'DEMO',{'ticker':'069500','market':'KR'},10,0);r=restore_backup(backup_bytes(w));self.assertEqual(r['holdings'].iloc[-1].ticker,'069500')
 def test_cached_quote_revaluation_and_category_totals(self):
  h=ws()['holdings'];h.loc[0,'shares']=10;h.loc[h.ticker.eq('CASH'),'shares']=1000
  v,e=m.valuation(h,DAY,fetch);updated,_,_=m.adjust(h,'DEMO','360750',5,'매수');r=m.revalue(v,updated)
  self.assertEqual(r.close.iloc[0],v.close.iloc[0]);self.assertEqual(r.value.iloc[0],15*113)
  self.assertAlmostEqual(r.weight.iloc[0],1695/2695*100)
  grouped=m.category_distribution(r);self.assertAlmostEqual(grouped.value.sum(),r.value.sum())
  self.assertEqual(set(grouped.category),{'선진국 주식','현금'})
if __name__=='__main__':unittest.main()
