import unittest
import pandas as pd
from streamlit_app.checkup import check, describe
from streamlit_app.data import normalize_holdings, normalize_strategies


def holdings(rows):
    cols=['strategy','account','ticker','name','market','category','role','target_pct','shares']
    return normalize_holdings(pd.DataFrame([dict(zip(cols,r)) for r in rows]))


class CheckupTests(unittest.TestCase):
    def test_target_sum_roles_and_gold(self):
        h=holdings([('SSO','일반계좌 2','SSO','SSO','US','선진국 주식','-10% 트리거',30,1),('SSO','일반계좌 2','QQQ','QQQ','US','선진국 주식','',100,1),
                    ('SSO','일반계좌 2','CASH','현금','KR','현금','현금',0,0),('GOLD','금 현물','GC=F','금','US','금','',100,1)])
        out={r['code']:r for r in check(h)}
        self.assertEqual(out['SSO']['status'],'문제')
        texts=' '.join(t for _,t in out['SSO']['issues'])
        self.assertIn('130%',texts);self.assertIn('「-10% 트리거」',texts)
        self.assertIn('GOLD_G',' '.join(t for _,t in out['GOLD']['issues']))
        self.assertEqual([r['code'] for r in check(h)][-1],'GOLD')  # both are 문제; order is stable

    def test_digit_ticker_marked_us(self):
        h=holdings([('HANA','일반계좌 1','5930','삼성전자','US','신흥국 주식','',100,1)])
        self.assertIn('6자리',check(h)[0]['issues'][0][1])

    def test_clean_account_and_rule_sentence(self):
        h=holdings([('ISA','ISA','225040','S&P 2배','KR','선진국 주식','레버리지',100,1),('ISA','ISA','CASH','현금','KR','현금','현금',0,0)])
        s=normalize_strategies(pd.DataFrame([dict(code='ISA',rule='isa_trend',params_json='{"mode":"trend","signal":"SPY"}',account='ISA')]))
        r=check(h,s)[0]
        self.assertEqual((r['status'],r['judged']),('정상',True));self.assertIn('SPY가 10개월 평균선 위면',r['rule'])
        self.assertIn('보유만',describe('HANA',{}))

    def test_price_missing_and_large_gap_use_the_view(self):
        h=holdings([('GSM','연금','133690','나스닥100','KR','선진국 주식','',80,1),('GSM','연금','CASH','현금','KR','현금','현금',20,0)])
        v=h.assign(value=[100.,0.],weight=[100.,0.])
        self.assertIn('차이가 큽니다',check(h,view=v)[0]['issues'][0][1])
        v2=h.assign(value=[float('nan'),0.],weight=[float('nan'),float('nan')])
        self.assertIn('가격을 불러오지 못한',check(h,view=v2)[0]['issues'][0][1])

    def test_shared_account_name(self):
        h=holdings([('HANA','일반계좌 1','CASH','현금','KR','현금','현금',100,0),('EM','일반계좌 1','CASH','현금','KR','현금','현금',100,0)])
        self.assertTrue(all(any('같은 계좌 이름' in t for _,t in r['issues']) for r in check(h)))



class KspTests(unittest.TestCase):
    def test_ksp_waits_for_the_2027_template(self):
        from datetime import date
        from streamlit_app import rules
        v=pd.DataFrame([dict(strategy='KSP',ticker='CASH',name='현금',role='현금',close=1.,sma10=None,return12=None,weight=100.,target_pct=100.,value=1.),
                        dict(strategy='EM',ticker='005930',name='삼성전자',role='',close=1.,sma10=None,return12=None,weight=100.,target_pct=100.,value=1.)])
        out={d['code']:d for d in rules.evaluate(v,date(2026,11,30),None)}
        self.assertEqual(out['KSP']['status'],'판정 없음');self.assertIn('2027',out['KSP']['headline'])
        self.assertEqual(out['EM']['status'],'판정 없음')
        self.assertFalse(check(holdings([('KSP','하나','CASH','현금','KR','현금','현금',100,0)]))[0]['judged'])
        self.assertIn('국내 주식 50%',describe('KSP',{'mode':'kr_half','kr_share':50}))


if __name__=='__main__':unittest.main()
