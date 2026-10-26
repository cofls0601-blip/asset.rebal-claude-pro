import unittest
import pandas as pd
from streamlit_app.tables import portfolio_table, weight_html
class TableTests(unittest.TestCase):
 def test_weight_comparison_display_precision_and_missing(self):
  for current,target,state in [(30,20,'over'),(10,20,'under'),(20,20,'equal'),(19.999999,20,'equal'),(20.006,20,'over'),(float('nan'),20,'neutral'),(20,float('nan'),'neutral')]:
   self.assertIn('weight-'+state,weight_html(current,target))
  self.assertIn('—',weight_html(float('nan'),20))
 def test_price_order_format_escaping_mobile_fields(self):
  v=pd.DataFrame([dict(strategy='TEST',ticker='QQQ',name='<script>alert(1)</script>',shares=10,market='US',close=12345.67,sma10=11234.56,value=1000000,weight=20,target_pct=25,return12=-3.5)])
  html=portfolio_table(v)
  self.assertIn('12,345.67',html);self.assertIn('11,234.56',html);self.assertIn('1,000,000',html)
  self.assertNotIn('<script>',html);self.assertIn('&lt;script&gt;',html)
  self.assertLess(html.index('>종가</th>'),html.index('>10개월 SMA</th>'))
  self.assertIn('portfolio-mobile',html);self.assertIn('12개월 수익률',html)
  self.assertEqual(html.count('weight-under'),2)
if __name__=='__main__':unittest.main()
