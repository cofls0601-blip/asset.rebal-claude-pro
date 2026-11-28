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
  at=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'streamlit_app.py')).run();at.radio(key='page').set_value('설정').run();return at
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
  editors=[e for e in at.dataframe if '보유수량' in list(e.value.columns)];self.assertTrue(editors)  # the holdings editor, not the check-up one
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
   at.radio(key='page').set_value(page).run();self.assertFalse(at.exception)
  at.radio(key='page').set_value('주문안').run();at.number_input[0].set_value(2);self.click(at,'매수');self.assertEqual(at.session_state['holdings'].shares.iloc[0],12)
  self.assertEqual(len(at.session_state['actions']),1)
  updated=at.session_state['valued']['view']
  self.assertEqual(updated.value.iloc[0],1200)
  self.assertAlmostEqual(updated.weight.iloc[0],1200/2200*100)
  self.assertEqual(updated.close.iloc[0],100)
  at.radio(key='page').set_value('리밸런싱').run()
  self.assertEqual(list(at.dataframe[0].value.columns),['티커','종목명','현재 비중','목표 비중'])
  at.radio(key='page').set_value('이번달').run();self.assertFalse(at.exception)
  shown=' '.join(x.value for x in at.markdown);self.assertIn('총자산',shown);self.assertIn('전일',shown);self.assertIn('목표·현재 도넛',shown);self.assertIn('이번 달 할 일',shown)

 def test_monthly_check_proposes_and_applies_only_on_click(self):
  at=self.start()
  h=pd.DataFrame([dict(strategy='SSO',account='일반계좌 2',ticker='SSO',name='ProShares Ultra S&P500',market='US',category='선진국 주식',role='',target_pct=70.,shares=7.),
                  dict(strategy='SSO',account='일반계좌 2',ticker='CASH',name='현금',market='KR',category='현금',role='현금',target_pct=30.,shares=300.)])
  at.session_state['holdings']=m.validate_holdings(h);day=at.sidebar.date_input[0].value
  idx=pd.bdate_range(end=pd.Timestamp(day),periods=260);spy=pd.Series(100.,index=idx);spy.iloc[-1]=84.
  fetch=lambda t,market,d:spy if t=='SPY' else pd.Series([100. if t=='SSO' else 1.],index=[pd.Timestamp(d)])
  v,e=m.valuation(at.session_state['holdings'],day,fetch);at.session_state['valued']={'date':str(day),'view':v,'errors':e}
  with patch.object(m,'fetch_prices',side_effect=fetch):
   at.radio(key='page').set_value('월말 점검').run();self.assertFalse(at.exception)
   self.assertEqual(at.session_state['holdings'].target_pct.tolist(),[70.,30.])
   self.click(at,'목표 비중에 반영')
  self.assertEqual(at.session_state['holdings'].target_pct.tolist(),[85.,15.])

 def test_add_gold_row(self):
  at=self.start();self.click(at,'금 현물(g) 항목 추가')
  row=at.session_state['holdings'].loc[lambda h:h.ticker.eq('GOLD_G')].iloc[0];self.assertEqual((row.category,row.market),('금','US'))
  self.assertFalse(any(x.label=='금 현물(g) 항목 추가' for x in at.button))

 def test_guided_rebalancing_flow(self):
  at=self.start()
  h=pd.DataFrame([dict(strategy='SSO',account='일반계좌 2',ticker='SSO',name='ProShares Ultra S&P500',market='US',category='선진국 주식',role='',target_pct=70.,shares=7.),
                  dict(strategy='SSO',account='일반계좌 2',ticker='CASH',name='현금',market='KR',category='현금',role='현금',target_pct=30.,shares=300.)])
  at.session_state['holdings']=m.validate_holdings(h)
  def fetch(t,market,d):
   if t=='SPY':idx=pd.bdate_range(end=pd.Timestamp(d),periods=260);s=pd.Series(100.,index=idx);s.iloc[-1]=84.;return s
   return pd.Series([100. if t=='SSO' else 1.],index=[pd.Timestamp(d)])
  with patch.object(m,'fetch_prices',side_effect=fetch):
   at.radio(key='page').set_value('월말 리밸런싱').run();self.assertFalse(at.exception)
   self.click(at,'판정 보기')
   html=' '.join(x.value for x in at.markdown);self.assertIn('이번 달 할 일 1개',html);self.assertIn('매수 1주',html)
   self.assertEqual(at.session_state['holdings'].target_pct.tolist(),[70.,30.])  # nothing changes before the click
   self.click(at,'체결하러 가기 (1개 계좌)')
   self.assertEqual(at.session_state['holdings'].target_pct.tolist(),[85.,15.]);self.assertEqual(at.session_state['rstep'],3)
   next(b for b in at.button if b.label=='체결 반영').click().run();self.assertFalse(at.exception)
   self.assertEqual(at.session_state['holdings'].shares.tolist(),[8.,200.]);self.assertEqual(len(at.session_state['actions']),1)
   self.assertFalse(any(b.label=='체결 반영' for b in at.button))
   self.assertIn('주문 1건 중 1건 반영',' '.join(x.value for x in at.markdown))
   self.click(at,'마감하러 가기');self.click(at,'이번 달 마감')
  self.assertEqual(len(at.session_state['snapshots']),2);self.assertEqual(at.session_state['rstep'],1)

 def test_2027_accounts_on_monthly_rebalancing(self):
  import json
  import streamlit as st
  from streamlit_app.data import normalize_strategies
  st.cache_data.clear();self.addCleanup(st.cache_data.clear)  # app caches prices; keep fake prices out of other tests
  at=self.start()
  rows=[('DAA','과세 연금저축',t,t,'KR',10.) for t in ['360750','133690','195970','195980','411060','308620','476760','153130']]+[('DAA','과세 연금저축','CASH','현금','KR',100000.)]
  rows+=[('ISA','ISA','225040','TIGER 미국S&P500레버리지(합성 H)','KR',0.),('ISA','ISA','153130','KODEX 단기채권','KR',10.),('ISA','ISA','CASH','현금','KR',0.)]
  rows+=[('KSP','일반계좌 1','005930','삼성전자','KR',10.),('KSP','일반계좌 1','SPY','SPDR S&P 500 ETF','US',1.),('KSP','일반계좌 1','CASH','현금','KR',0.)]
  h=pd.DataFrame([dict(strategy=c,account=a,ticker=t,name=n,market=mk,category='현금' if t in ('CASH','153130') else '선진국 주식',
                       role='레버리지' if t=='225040' else '',target_pct=0.,shares=q) for c,a,t,n,mk,q in rows])
  at.session_state['holdings']=m.validate_holdings(h)
  params={'DAA':{},'ISA':{'mode':'trend','signal':'SPY','cash':'153130'},
          'KSP':{'mode':'kr_half','kr_share':50,'signal':'069500','spx':'SPY','month':12,'max_pct':30,'start':'2027-01'}}
  at.session_state['strategies']=normalize_strategies(pd.DataFrame([dict(code=c,account=a,rule='',params_json=json.dumps(p))
                                                                    for (c,p),a in zip(params.items(),['과세 연금저축','ISA','일반계좌 1'])]))
  growth={'133690':.30,'360750':.20,'411060':.15,'195970':.02,'195980':.05,'308620':.01,'476760':-.05,'153130':.03,
          'AGG':.04,'SPY':.15,'069500':.10,'225040':.3,'005930':.1,'KRW=X':0.}
  def fetch(t,market,d,adjusted=False):
   idx=pd.bdate_range(end=pd.Timestamp(d),periods=420)
   g=growth.get(t,0.);base=1300. if t=='KRW=X' else 100.
   return pd.Series([base*(1+g)**(i/252) for i in range(len(idx))],index=idx)
  with patch.object(m,'fetch_prices',side_effect=fetch):
   at.radio(key='page').set_value('월말 리밸런싱').run();self.assertFalse(at.exception)
   self.click(at,'판정 보기')
   html=' '.join(x.value for x in at.markdown)
   self.assertIn('위험 신호 0개 → 공격 100%',html)
   self.assertIn('133690·360750·411060',html)
   self.assertIn('SPY SMA 위 → TIGER 미국S&amp;P500레버리지(합성 H) 100%',html)
   self.assertIn('그대로',html)
   self.click(at,'체결하러 가기 (2개 계좌)')
  daa=at.session_state['holdings'].query("strategy=='DAA'").set_index('ticker').target_pct
  self.assertAlmostEqual(daa['133690'],100/3,places=3);self.assertEqual(daa['476760'],0.)
  isa=at.session_state['holdings'].query("strategy=='ISA'").set_index('ticker').target_pct
  self.assertEqual(isa['225040'],100.)

 def test_account_checkup_flags_and_fixes_target_sum(self):
  at=self.start()
  h=pd.DataFrame([dict(strategy='SSO',account='일반계좌 2',ticker='SSO',name='ProShares Ultra S&P500',market='US',category='선진국 주식',role='-10% 트리거',target_pct=100.,shares=1.),
                  dict(strategy='SSO',account='일반계좌 2',ticker='CASH',name='현금',market='KR',category='현금',role='현금',target_pct=30.,shares=0.)])
  at.session_state['holdings']=m.validate_holdings(h);at.run();self.assertFalse(at.exception)
  self.assertTrue(any('130%' in e.value for e in at.error));self.assertTrue(any('「-10% 트리거」' in w.value for w in at.warning))
  editor=next(e for e in at.dataframe if '역할' in list(e.value.columns))
  at.session_state[editor.proto.id]={'edited_rows':{0:{'역할':'레버리지','목표 (%)':70}},'added_rows':[],'deleted_rows':[]}
  next(b for b in at.button if b.label=='저장').click().run();self.assertFalse(at.exception)
  self.assertEqual(at.session_state['holdings'].target_pct.tolist(),[70.,30.]);self.assertEqual(at.session_state['holdings'].role.iloc[0],'레버리지')
  self.assertFalse(any('130%' in e.value for e in at.error))

 def test_checkup_renames_codes_but_keeps_account_names(self):
  at=self.start()
  h=pd.DataFrame([dict(strategy='EM',account='삼성 소액',ticker='005930',name='삼성전자',market='KR',category='신흥국 주식',role='',target_pct=100.,shares=1.),
                  dict(strategy='HANA',account='하나',ticker='CASH',name='현금',market='KR',category='현금',role='현금',target_pct=100.,shares=0.)])
  at.session_state['holdings']=m.validate_holdings(h);at.run()
  sb=at.selectbox(key='rule_forHANA');sb.select_index([o.split(' · ')[0] for o in sb.options].index('KSP')).run()  # options show 'KSP · 규칙 설명'
  next(b for b in at.button if b.label=='HANA → KSP로 바꾸기').click().run();self.assertFalse(at.exception)
  got=at.session_state['holdings'].set_index('strategy').account.to_dict()
  self.assertEqual(got,{'EM':'삼성 소액','KSP':'하나'})
  at.selectbox(key='rule_forEM').set_value('직접 입력(규칙 없음)').run();at.text_input(key='rule_textEM').set_value('etc').run()
  next(b for b in at.button if b.label=='EM → ETC로 바꾸기').click().run();self.assertFalse(at.exception)  # free-text rename still works
  self.assertIn('ETC',set(at.session_state['holdings'].strategy))

 def test_sheets_save_feedback_on_main_page(self):
  import hashlib
  from streamlit_app import sheets_sync
  from streamlit_app.ledger import empty_workspace
  from streamlit_app.data import load_default_holdings
  w=empty_workspace();w['holdings']=load_default_holdings();saves=[]
  def save(url,secret,workspace,token,**k):saves.append(token);return 'tok'+str(len(saves)+1)
  with patch.object(sheets_sync,'load_workspace',return_value=(w,'tok1')),patch.object(sheets_sync,'save_workspace',side_effect=save):
   at=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'streamlit_app.py'))
   pw='p'*12;at.secrets['SHEETS_WEBAPP_URL']='https://script.google.com/macros/s/x/exec';at.secrets['SHEETS_SECRET']='s'*24;at.secrets['APP_PASSWORD']=pw
   at.session_state['auth']=hashlib.sha256(pw.encode()).hexdigest();at.run();at.radio(key='page').set_value('설정').run();self.assertFalse(at.exception)
   self.click(at,'금 현물(g) 항목 추가')  # an edit saves by itself
   self.assertEqual(saves,['tok1']);self.assertTrue(any('Sheets에 저장했습니다' in x.value for x in at.success))
   next(b for b in at.sidebar.button if b.label=='Sheets에 저장').click().run();self.assertFalse(at.exception)
   self.assertEqual(saves,['tok1','tok2']);self.assertTrue(any('Sheets에 저장했습니다 (' in x.value for x in at.success))
  with patch.object(sheets_sync,'save_workspace',side_effect=sheets_sync.SheetsError('다른 세션 또는 시트에서 자료가 바뀌었습니다')):
   next(b for b in at.sidebar.button if b.label=='Sheets에 저장').click().run()
   self.assertTrue(any('Sheets 저장 실패' in x.value for x in at.error))

if __name__=='__main__':unittest.main()
