import unittest
from unittest.mock import patch,Mock
import sys
import pandas as pd
from streamlit_app import manual as m
from streamlit_app.data import DataError

class SearchTests(unittest.TestCase):
 def test_qqq_works_without_network(self):
  with patch('yfinance.Ticker',side_effect=RuntimeError('offline')),patch('yfinance.Search',side_effect=RuntimeError('rate limit')):
   results=m.search('qqq','KR');self.assertEqual(results[0]['ticker'],'QQQ')
 def test_domestic_etf_and_stock_sources(self):
  fdr=Mock();fdr.StockListing.side_effect=lambda name:pd.DataFrame([{'Symbol':'123456','Name':'테스트 ETF'}]) if name=='ETF/KR' else pd.DataFrame([{'Code':'005930','Name':'테스트 주식'}])
  with patch.dict(sys.modules,{'FinanceDataReader':fdr}),patch('yfinance.Search',return_value=Mock(quotes=[])):
   results=m.search('테스트','KR');self.assertEqual({r['ticker'] for r in results},{'123456','005930'})
   self.assertEqual([x.args[0] for x in fdr.StockListing.call_args_list],['ETF/KR','KRX'])
 def test_failed_search_is_explicit_and_can_retry(self):
  with patch('yfinance.Ticker',side_effect=RuntimeError('offline')),patch('yfinance.Search',side_effect=RuntimeError('rate limit')):
   self.assertTrue(m.search('ZZZZ','KR')[0]['unverified'])
  with patch('yfinance.Ticker',return_value=Mock(info={'shortName':'Test asset'})),patch('yfinance.Search',return_value=Mock(quotes=[])):
   self.assertEqual(m.search('ZZZZ','US')[0]['ticker'],'ZZZZ')
 def test_arbitrary_unheld_symbols_lookup(self):
  for ticker in ['MAGX','NVDL','QQQ']:
   with patch('yfinance.Ticker',return_value=Mock(info={'shortName':'Resolved '+ticker})) as lookup,patch('yfinance.Search',return_value=Mock(quotes=[])):
    result=m.search(ticker,'KR');self.assertEqual(result[0]['ticker'],ticker);self.assertEqual(result[0]['market'],'US');self.assertEqual(result[0]['name'],'Resolved '+ticker);lookup.assert_called_with(ticker)
 def test_name_mode_preserves_domestic_brand_search(self):
  fdr=Mock();fdr.StockListing.return_value=pd.DataFrame([{'Code':'123456','Name':'TIGER 테스트'}])
  with patch.dict(sys.modules,{'FinanceDataReader':fdr}),patch('yfinance.Search',return_value=Mock(quotes=[])):
   self.assertIn('123456',[r['ticker'] for r in m.search('TIGER','KR',mode='name')])
if __name__=='__main__':unittest.main()
