import unittest
from datetime import date
import pandas as pd
from streamlit_app import manual as m
from streamlit_app.tables import change_html


def holdings():
    return pd.DataFrame([dict(strategy='A',account='연금',ticker='069500',name='KODEX 200',market='KR',category='신흥국 주식',role='',target_pct=50,shares=10),
                         dict(strategy='A',account='연금',ticker='QQQ',name='QQQ',market='US',category='선진국 주식',role='',target_pct=50,shares=2),
                         dict(strategy='A',account='연금',ticker='CASH',name='현금',market='KR',category='현금',role='현금',target_pct=0,shares=500)])


def fetch(t,market,day):
    idx=pd.to_datetime(['2026-10-26','2026-10-27'])
    return pd.Series({'KRW=X':[1400.,1500.],'QQQ':[100.,110.]}.get(t,[1000.,900.]),index=idx)


class TotalTests(unittest.TestCase):
    def test_previous_day_value_uses_same_quantity(self):
        v,e=m.valuation(holdings(),date(2026,10,27),fetch);self.assertFalse(e)
        self.assertEqual(v.prev_value.tolist(),[10*1000,2*100*1400,500])
        self.assertEqual(v.value.tolist(),[10*900,2*110*1500,500])
        r=m.revalue(v,holdings().assign(shares=[11,2,500]))
        self.assertEqual(r.prev_value.iloc[0],11*1000)

    def test_change_colors_follow_korean_convention(self):
        self.assertIn('change up',change_html(110,100,'전일'));self.assertIn('▲ 10원 · +10.00%',change_html(110,100,'전일'))
        self.assertIn('change down',change_html(90,100,'전일'));self.assertIn('▼',change_html(90,100,'전일'))
        self.assertIn('—',change_html(100,None,'지난 기록'));self.assertIn('—',change_html(None,100,'전일'))
        self.assertIn('&lt;b&gt;',change_html(1,1,'<b>'))

    def test_last_record_uses_latest_earlier_date_and_revision(self):
        s=pd.DataFrame([dict(date='2026-09-30',strategy='A',value=100,revision=1),dict(date='2026-09-30',strategy='B',value=50,revision=1),
                        dict(date='2026-09-30',strategy='A',value=120,revision=2),dict(date='2026-09-30',strategy='B',value=60,revision=2),
                        dict(date='2026-10-27',strategy='A',value=999,revision=1),dict(date='2026-08-31',strategy='A',value=1,revision=1)])
        self.assertEqual(m.last_record(s,date(2026,10,27)),('2026-09-30',180.,{'A':120.,'B':60.}))
        self.assertIsNone(m.last_record(s,date(2026,8,31)))
        self.assertIsNone(m.last_record(pd.DataFrame(columns=['date','strategy','value']),date(2026,10,27)))


if __name__=='__main__':unittest.main()


class ReconcileTests(unittest.TestCase):
    def test_per_account_difference(self):
        v=pd.DataFrame(dict(account=['연금','연금','ISA'],value=[600.,400.,500.]))
        r=m.reconcile(v,{'연금':1004.,'ISA':450.,'없는 계좌':1.})
        self.assertEqual(r['계좌'].tolist(),['연금','ISA'])
        self.assertEqual(r['차이'].tolist(),[-4.,50.]);self.assertEqual(r['판정'].tolist(),['일치','차이 큼'])
        self.assertTrue(m.reconcile(v,{'연금':0.}).empty)
