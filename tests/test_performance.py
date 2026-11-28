import unittest
from datetime import date
import pandas as pd
from streamlit_app.data import DataError
from streamlit_app.performance import add_cashflow, net_flow, summary, xirr

H=pd.DataFrame(dict(strategy=['KSP','GSM'],account=['하나','비과세 연금저축']))
CF=pd.DataFrame(columns=['date','amount','memo','strategy','kind','transfer_id'])


class PerformanceTests(unittest.TestCase):
    def test_add_cashflow_finds_the_code_and_rejects_bad_amounts(self):
        cf=add_cashflow(CF,H,date(2026,11,28),'하나',1_000_000,'적립')
        self.assertEqual(cf.iloc[0][['strategy','amount','kind']].tolist(),['KSP',1_000_000,'입금'])
        self.assertEqual(add_cashflow(cf,H,date(2026,11,29),'하나',-200_000).iloc[1].kind,'출금')
        for bad in [0,'x',float('nan')]:
            with self.assertRaises(DataError):add_cashflow(CF,H,date(2026,11,28),'하나',bad)
        with self.assertRaises(DataError):add_cashflow(CF,H,date(2026,11,28),'없는 계좌',1)

    def test_xirr_matches_simple_cases(self):
        self.assertAlmostEqual(xirr([(date(2025,1,1),100.)],110.,date(2026,1,1)),10.,places=3)
        # 100 a year ago and 100 today (just deposited) worth 210 → only the first 100 earned 10%.
        self.assertAlmostEqual(xirr([(date(2025,1,1),100.),(date(2026,1,1),100.)],210.,date(2026,1,1)),10.,places=3)
        self.assertIsNone(xirr([],1.,date(2026,1,1)))

    def test_summary_principal_return_and_annual_only_after_a_year(self):
        cf=pd.DataFrame([dict(date='2024-11-28',amount=60_000_000,strategy='KSP'),dict(date='2026-06-01',amount=-5_000_000,strategy='KSP'),
                         dict(date='2026-01-01',amount=1_000_000,strategy='GSM')])
        s=summary(93_587_466,cf,date(2026,11,28),codes=['KSP'])
        self.assertEqual(s['principal'],55_000_000);self.assertAlmostEqual(s['return_pct'],(93_587_466/55_000_000-1)*100)
        self.assertGreater(s['annual_pct'],0)
        young=summary(1_100_000,cf,date(2026,11,28),codes=['GSM'])
        self.assertIsNone(young['annual_pct'])                     # under a year: no yearly figure
        self.assertIsNone(summary(1.,CF,date(2026,11,28)))          # no 입출금 yet

    def test_net_flow_strips_deposits_from_a_change(self):
        cf=pd.DataFrame([dict(date='2026-10-31',amount=500,strategy='KSP'),dict(date='2026-11-10',amount=300,strategy='KSP'),
                         dict(date='2026-11-20',amount=-100,strategy='GSM')])
        self.assertEqual(net_flow(cf,date(2026,10,31),date(2026,11,28)),200)   # after the 10-31 record
        self.assertEqual(net_flow(cf,date(2026,10,31),date(2026,11,28),codes=['KSP']),300)


if __name__=='__main__':unittest.main()
