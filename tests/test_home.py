import unittest
import pandas as pd
from streamlit_app import home, ui


class FormatTests(unittest.TestCase):
    def test_won_units(self):
        self.assertEqual(ui.won(324_800_000),'3억 2,480만원');self.assertEqual(ui.won(84_120_000,unit=False),'8,412만')
        self.assertEqual(ui.won(100_000_000),'1억원');self.assertEqual(ui.won(9_500),'9,500원');self.assertEqual(ui.won(-6_150_000),'-615만원')
        self.assertIn('<small>만원</small>',ui.won_big(324_800_000))

    def test_colors_follow_meaning(self):
        self.assertEqual(ui.strategy_color('DAA'),ui.strategy_color('LAA'));self.assertEqual(ui.strategy_color('SPX'),ui.strategy_color('SSO'))
        self.assertEqual(ui.asset_color('금'),'#C9A227');self.assertEqual(ui.strategy_color('NEW'),ui.OTHER)
        self.assertIn('ds-w over',ui.weight_text(63.9,40));self.assertIn('ds-w same',ui.weight_text(20.3,20));self.assertIn('ds-w under',ui.weight_text(0,40))
        self.assertIn('ds-chg up',ui.change(110e6,100e6));self.assertIn('ds-chg down',ui.change(90e6,100e6));self.assertIn('—',ui.change(1,None))


class HomeTests(unittest.TestCase):
    def view(self):
        return pd.DataFrame([dict(strategy='GSM',account='비과세 연금저축',ticker='133690',name='TIGER 미국나스닥100',category='선진국 주식',shares=41,value=53_710_000,weight=63.9,target_pct=40),
                             dict(strategy='GSM',account='비과세 연금저축',ticker='CASH',name='현금',category='현금',shares=0,value=30_410_000,weight=36.1,target_pct=60),
                             dict(strategy='GOLD',account='금 현물',ticker='GOLD_G',name='금 현물',category='금',shares=120,value=18_400_000,weight=100,target_pct=100)])

    def test_account_list_and_status(self):
        html=home.account_list(self.view(),{'GSM':True},{},{'GSM':1.2})
        self.assertIn('비과세 연금저축',html);self.assertIn('금 현물 120g',html);self.assertIn('판정함',html);self.assertIn('국제시세 추정',html)
        self.assertIn('41주 · 5,371만원',html);self.assertIn('63.9%',html)
        self.assertIn('문제 1',home.account_status('LAA',True,{'issues':[('문제','x')]}))

    def test_monthly_takes_last_record_and_revision_of_each_month(self):
        s=pd.DataFrame([dict(date='2026-10-30',strategy='GSM',account='비과세',category='선진국 주식',value=100,revision=1),
                        dict(date='2026-10-31',strategy='GSM',account='비과세',category='선진국 주식',value=110,revision=1),
                        dict(date='2026-10-31',strategy='GSM',account='비과세',category='선진국 주식',value=120,revision=2),
                        dict(date='2026-11-30',strategy='ISA',account='ISA',category='현금',value=50,revision=1)])
        m=home.monthly(s)
        self.assertEqual(m.value.tolist(),[120,50]);self.assertEqual(m.account.tolist(),['비과세','ISA'])
        self.assertEqual(home.monthly(s,'category').key.tolist(),['선진국 주식','현금'])
        self.assertTrue(home.monthly(pd.DataFrame()).empty)


    def test_todo_kind(self):
        self.assertEqual(home.todo_kind(dict(current={'A':80,'B':0,'CASH':20},targets={'A':0,'B':80,'CASH':20})),'사고팔기')
        self.assertEqual(home.todo_kind(dict(current={'A':70,'CASH':30},targets={'A':85,'CASH':15})),'매수')
        self.assertEqual(home.todo_kind(dict(current={'A':25,'CASH':0},targets={'A':0,'CASH':25})),'매도')

    def test_expected_weights_follow_new_quantities(self):
        v=pd.DataFrame([dict(ticker='A',shares=1,close=100.,fx=1.),dict(ticker='B',shares=1,close=10.,fx=10.),dict(ticker='CASH',shares=200,close=1.,fx=1.)])
        w,total=home.expected_weights(v,{'A':3})                 # A 300, B 100, cash 200
        self.assertEqual(total,600);self.assertAlmostEqual(w['A'],50);self.assertAlmostEqual(w['CASH'],100/3)
        self.assertIsNone(home.expected_weights(v.assign(close=[float('nan'),10.,1.]),{}))

if __name__=='__main__':unittest.main()
