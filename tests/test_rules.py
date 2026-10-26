import unittest
from datetime import date
import pandas as pd
from streamlit_app import rules as r

DAY=date(2026,10,30)  # not a quarter month


def view(code,rows):
    cols=['ticker','name','role','close','sma10','return12','weight','target_pct']
    v=pd.DataFrame([dict(zip(cols,x)) for x in rows]);v.insert(0,'strategy',code);return v


def prices(dd):
    """Daily closes for a year that peak at 100 and end `dd`% below the peak."""
    idx=pd.bdate_range(end=pd.Timestamp(DAY),periods=260)
    s=pd.Series(100.,index=idx);s.iloc[-1]=100+dd;return lambda t,m,d:s


def gsm(*stats):
    names=['TIGER 미국나스닥100','TIGER 미국S&P500','KODEX MSCI선진국','TIGER 유로스탁스배당30']
    rows=[(f'T{i}',names[i],'',c,s,ret,20.,0.) for i,(c,s,ret) in enumerate(stats)]
    return view('GSM',rows+[('CASH','현금','현금',1,None,None,20.,100.)])


class GSMTests(unittest.TestCase):
    def test_top_return_among_assets_above_sma(self):
        # T0 has the best return but is below SMA, so T2 wins.
        d=r.check_gsm(gsm((90,100,30),(110,100,10),(120,100,20),(105,100,5)),DAY,None)
        self.assertEqual(d['targets'],{'T0':0,'T1':0,'T2':80,'T3':0,'CASH':20})
        self.assertIn('KODEX MSCI선진국',d['headline'])

    def test_all_below_sma_goes_to_cash(self):
        d=r.check_gsm(gsm((90,100,30),(90,100,10),(90,100,20),(90,100,5)),DAY,None)
        self.assertEqual(d['targets']['CASH'],100)

    def test_missing_indicator_blocks(self):
        d=r.evaluate(gsm((90,None,30),(110,100,10),(120,100,20),(105,100,5)),DAY,None)[0]
        self.assertEqual(d['status'],'계산 불가')


def laa(nasdaq_close,euro_close,weights=(12.5,12.5,12.5,12.5,25,25,0)):
    rows=[('N','RISE 미국나스닥100',''),('E','TIGER 유로스탁스배당30',''),('S','RISE 미국S&P500',''),('W','KODEX MSCI선진국',''),
          ('G','ACE KRX금현물',''),('B','KODEX 미국10년국채선물',''),('CASH','현금','현금')]
    closes=[nasdaq_close,euro_close,100,100,100,100,1]
    targets=[12.5,12.5,12.5,12.5,25,25,0]
    return view('LAA',[(t,n,role,c,100,0,w,tg) for (t,n,role),c,w,tg in zip(rows,closes,weights,targets)])


class LAATests(unittest.TestCase):
    def test_only_filter_assets_below_sma_move_to_cash(self):
        d=r.check_laa(laa(90,110),DAY,None)
        self.assertEqual(d['targets']['N'],0);self.assertEqual(d['targets']['E'],12.5);self.assertEqual(d['targets']['CASH'],12.5)
        self.assertEqual(d['targets']['S'],12.5)

    def test_non_quarter_month_keeps_drifted_weights(self):
        drift=(10,15,13,12,25,25,0)
        d=r.check_laa(laa(110,110,drift),DAY,None)
        self.assertFalse(d['changed']);self.assertIn('유지',d['headline'])

    def test_quarter_end_restores_targets_except_filtered(self):
        drift=(0,15,13,12,25,25,10)
        d=r.check_laa(laa(110,90,drift),date(2026,12,31),None)
        self.assertEqual(d['targets']['N'],12.5);self.assertEqual(d['targets']['E'],0);self.assertEqual(d['targets']['CASH'],12.5)

    def test_filter_role_overrides_name_match(self):
        v=laa(110,110);v.loc[v.ticker.eq('S'),'role']='필터';v.loc[v.ticker.eq('S'),'close']=90
        d=r.check_laa(v,DAY,None)
        self.assertEqual(d['targets']['S'],0);self.assertEqual(d['targets']['N'],12.5)


def ladder(code,weight,name='SSO'):
    return view(code,[('SSO' if code=='SSO' else '418660',name,'',100,None,None,weight,0),('CASH','현금','현금',1,None,None,100-weight,0)])


class LadderTests(unittest.TestCase):
    def test_sso_steps(self):
        cases=[(-10,70,70,'트리거 없음'),(-16,70,85,'1단계'),(-21,70,92.5,'2단계'),(-21,85,92.5,'2단계'),(-16,82,82,'이미 실행'),(0,92.5,70,'고점 회복')]
        for dd,weight,target,word in cases:
            with self.subTest(dd=dd,weight=weight):
                d=r.check_ladder('SSO',ladder('SSO',weight),DAY,prices(dd))
                self.assertAlmostEqual(d['targets']['SSO'],target);self.assertIn(word,d['headline'])

    def test_isa_steps(self):
        name='TIGER 미국나스닥100레버리지(합성)'
        cases=[(-5,0,0),(-11,0,100/3),(-16,100/3,200/3),(-25,0,100),(0,100,0)]
        for dd,weight,target in cases:
            with self.subTest(dd=dd,weight=weight):
                d=r.check_ladder('ISA',ladder('ISA',weight,name),DAY,prices(dd))
                self.assertAlmostEqual(d['targets']['418660'],target)

    def test_drawdown_uses_52_week_high(self):
        idx=pd.bdate_range(end=pd.Timestamp(DAY),periods=600)
        s=pd.Series(80.,index=idx);s.iloc[0]=200;s.iloc[-100]=100  # 200 is older than 52 weeks
        dd,close,high=r.drawdown(s,DAY)
        self.assertEqual(high,100);self.assertAlmostEqual(dd,-20)


class EvaluateTests(unittest.TestCase):
    def test_order_and_unjudged_strategies(self):
        v=pd.concat([view('EM',[('069500','KODEX 200','',100,None,None,100,100)]),ladder('SSO',70),
                     gsm((90,100,30),(110,100,10),(120,100,20),(105,100,5))])
        out=r.evaluate(v,DAY,prices(-5))
        self.assertEqual([d['code'] for d in out],['GSM','SSO','EM'])
        self.assertEqual(out[-1]['status'],'판정 없음')

    def test_apply_targets_writes_strategy_only(self):
        h=pd.DataFrame(dict(strategy=['SSO','SSO','EM'],ticker=['SSO','CASH','069500'],target_pct=[70.,30.,100.]))
        out=r.apply_targets(h,'SSO',{'SSO':85.,'CASH':15.})
        self.assertEqual(out.target_pct.tolist(),[85.,15.,100.])
        with self.assertRaises(Exception):r.apply_targets(h,'SSO',{'SSO':85.,'X':15.})


if __name__=='__main__':unittest.main()
