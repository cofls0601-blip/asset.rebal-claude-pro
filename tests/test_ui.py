import unittest
import logging
logging.disable(logging.CRITICAL)
from unittest.mock import patch
from datetime import date
from pathlib import Path
import pandas as pd
from streamlit.testing.v1 import AppTest
from streamlit_app import manual as m

class UITests(unittest.TestCase):
 def start(self):
  at=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'streamlit_app.py')).run();at.sidebar.radio[0].set_value('설정').run();return at
 def text(self,at,label,value):next(x for x in at.text_input if x.label==label).set_value(value)
 def click(self,at,label):next(x for x in at.button if x.label==label).click().run();self.assertFalse(at.exception)
 def test_strategy_add_rename_delete(self):
  at=self.start();self.text(at,'전략명','TEST');self.text(at,'계좌명','연금');self.click(at,'전략 추가');self.assertIn('TEST',at.session_state['holdings'].strategy.tolist())
  at.selectbox(key='manage_strategy').set_value('TEST').run();self.text(at,'전략명 변경','UPDATED');self.text(at,'계좌명 변경','ISA');self.click(at,'변경 적용')
  self.assertIn('UPDATED',at.session_state['holdings'].strategy.tolist())
  at.selectbox(key='manage_strategy').set_value('UPDATED').run();at.checkbox(key='delete_confirmUPDATED').check().run();self.click(at,'전략 삭제');self.assertNotIn('UPDATED',at.session_state['holdings'].strategy.tolist())
 def test_search_add_edit_delete_and_no_stale_hits(self):
  at=self.start();self.text(at,'티커 또는 종목명 검색','KODEX')
  with patch.object(m,'search',return_value=[{'ticker':'069500','name':'KODEX 200','market':'KR'}]):self.click(at,'종목 검색')
  self.click(at,'전략에 종목 추가');self.assertIn('069500',at.session_state['holdings'].ticker.tolist())
  self.text(at,'티커 또는 종목명 검색','OTHER');at.run();self.assertEqual(at.selectbox(key='settingsDEMOchoice').value,-1)
  # Simulate actual data-editor edit events and submit its form.
  editors=at.dataframe;self.assertTrue(editors)
  editor_key=editors[0].proto.id.split('-',2)[-1]
  # Streamlit's editor state uses the generated element id in AppTest.
  at.session_state[editors[0].proto.id]={'edited_rows':{0:{'보유수량':5,'목표비중 (%)':40}},'added_rows':[],'deleted_rows':[]}
  self.click(at,'보유수량·목표비중 적용')
  self.assertEqual(at.session_state['holdings'].shares.iloc[0],5)
  self.assertEqual(at.session_state['holdings'].target_pct.iloc[0],40)
  at.selectbox(key='delete_asset_selectDEMO').set_value('069500').run();self.click(at,'종목 삭제');self.assertNotIn('069500',at.session_state['holdings'].ticker.tolist())
 def test_priced_menus_and_order(self):
  at=self.start();h=at.session_state['holdings'].copy();h.loc[0,'shares']=10;h.loc[h.ticker.eq('CASH'),'shares']=1000;at.session_state['holdings']=h
  day=at.sidebar.date_input[0].value;v,e=m.valuation(h,day,lambda t,m,d:pd.Series([100.],index=[pd.Timestamp(d)]))
  at.session_state['valued']={'date':str(day),'view':v,'errors':e}
  for page in ['이번달','리밸런싱','주문안','기록']:
   at.sidebar.radio[0].set_value(page).run();self.assertFalse(at.exception)
  at.sidebar.radio[0].set_value('주문안').run();at.number_input[0].set_value(2);self.click(at,'매수');self.assertEqual(at.session_state['holdings'].shares.iloc[0],12)
  self.assertEqual(len(at.session_state['actions']),1)
  updated=at.session_state['valued']['view']
  self.assertEqual(updated.value.iloc[0],1200)
  self.assertAlmostEqual(updated.weight.iloc[0],1200/2200*100)
  self.assertEqual(updated.close.iloc[0],100)
  at.sidebar.radio[0].set_value('리밸런싱').run()
  self.assertEqual(list(at.dataframe[0].value.columns),['티커','종목명','현재 비중','목표 비중'])
  at.sidebar.radio[0].set_value('이번달').run();self.assertFalse(at.exception)
  shown=' '.join(x.value for x in at.markdown);self.assertIn('총자산',shown);self.assertIn('전일 대비',shown);self.assertIn('상세',shown)

 def test_monthly_check_proposes_and_applies_only_on_click(self):
  at=self.start()
  h=pd.DataFrame([dict(strategy='SSO',account='일반계좌 2',ticker='SSO',name='ProShares Ultra S&P500',market='US',category='선진국 주식',role='',target_pct=70.,shares=7.),
                  dict(strategy='SSO',account='일반계좌 2',ticker='CASH',name='현금',market='KR',category='현금',role='현금',target_pct=30.,shares=300.)])
  at.session_state['holdings']=m.validate_holdings(h);day=at.sidebar.date_input[0].value
  idx=pd.bdate_range(end=pd.Timestamp(day),periods=260);spy=pd.Series(100.,index=idx);spy.iloc[-1]=84.
  fetch=lambda t,market,d:spy if t=='SPY' else pd.Series([100. if t=='SSO' else 1.],index=[pd.Timestamp(d)])
  v,e=m.valuation(at.session_state['holdings'],day,fetch);at.session_state['valued']={'date':str(day),'view':v,'errors':e}
  with patch.object(m,'fetch_prices',side_effect=fetch):
   at.sidebar.radio[0].set_value('월말 점검').run();self.assertFalse(at.exception)
   self.assertEqual(at.session_state['holdings'].target_pct.tolist(),[70.,30.])
   self.click(at,'목표 비중에 반영')
  self.assertEqual(at.session_state['holdings'].target_pct.tolist(),[85.,15.])

 def test_add_gold_row(self):
  at=self.start();self.click(at,'금 현물(g) 항목 추가')
  row=at.session_state['holdings'].loc[lambda h:h.ticker.eq('GOLD_G')].iloc[0];self.assertEqual((row.category,row.market),('금','US'))
  self.assertFalse(any(x.label=='금 현물(g) 항목 추가' for x in at.button))

if __name__=='__main__':unittest.main()
