import json
import unittest

import pandas as pd

from streamlit_app.data import normalize_holdings, normalize_strategies
from streamlit_app.ledger import empty_workspace
from streamlit_app.template import apply_template, load_template, mapping_table


def workspace():
    h = normalize_holdings(pd.DataFrame([
        dict(strategy="GSM", account="비과세 연금저축", ticker="133690", name="TIGER 미국나스닥100", market="KR", category="선진국 주식", role="", target_pct=80, shares=10),
        dict(strategy="GSM", account="비과세 연금저축", ticker="CASH", name="현금", market="KR", category="현금", role="", target_pct=20, shares=1000),
        dict(strategy="EM", account="일반계좌 1", ticker="005930", name="삼성전자", market="KR", category="신흥국 주식", role="", target_pct=0, shares=5),
        dict(strategy="SSO", account="일반계좌 2", ticker="SSO", name="SSO", market="US", category="선진국 주식", role="", target_pct=70, shares=3),
        dict(strategy="SSO", account="일반계좌 2", ticker="CASH", name="현금", market="KR", category="현금", role="", target_pct=30, shares=100),
    ]))
    s = normalize_strategies(pd.DataFrame([dict(code="GSM", rule="momentum_rotate", params_json="{}", account="비과세 연금저축")]))
    return h, s, empty_workspace()["strategy_versions"]


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.t = load_template()

    def test_template_has_every_account_once(self):
        accounts = [s["account"] for s in self.t["strategies"]]
        self.assertEqual(len(accounts), len(set(accounts)))
        self.assertEqual(len(mapping_table(self.t)), len(accounts))

    def test_apply_keeps_shares_and_adds_missing_assets_with_zero(self):
        h, s, v = workspace()
        nh, ns, nv, changes = apply_template(h, s, v, self.t)
        self.assertEqual(float(nh.loc[(nh.strategy == "GSM") & (nh.ticker == "133690"), "shares"].iloc[0]), 10)
        self.assertEqual(float(nh.loc[(nh.strategy == "GSM") & (nh.ticker == "133690"), "target_pct"].iloc[0]), 80)  # null → 유지
        self.assertEqual(float(nh.loc[(nh.strategy == "GSM") & (nh.ticker == "411060"), "shares"].iloc[0]), 0)
        self.assertEqual(json.loads(ns.set_index("code").loc["GSM", "params_json"]), {"top": 2})
        self.assertEqual(len(nv), 1)  # 이전 GSM 설정 보관

    def test_strategies_not_in_template_are_left_alone(self):
        h, s, v = workspace()
        nh, _, _, changes = apply_template(h, s, v, self.t)
        self.assertEqual(float(nh.loc[(nh.strategy == "SSO") & (nh.ticker == "SSO"), "shares"].iloc[0]), 3)
        self.assertIn("SSO", set(changes["전략"]))

    def test_em_keeps_its_own_holdings(self):
        h, s, v = workspace()
        nh, *_ = apply_template(h, s, v, self.t)
        em = nh[nh.strategy == "EM"]
        self.assertEqual(set(em.ticker), {"005930", "CASH"})


if __name__ == "__main__":
    unittest.main()
