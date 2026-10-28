"""연도별 전략 템플릿(config/strategy_2027.json)을 전략표·보유표에 합친다.

보유 수량은 절대 바꾸지 않는다. 템플릿에 없는 전략(예: 2026 SSO)은 그대로 두고 안내만 한다.
"""
import json
from datetime import datetime, timezone

import pandas as pd

from streamlit_app.data import HOLDING_COLUMNS, STRATEGY_COLUMNS, DataError, normalize_holdings, normalize_strategies

TEMPLATE_PATH = "config/strategy_2027.json"


def load_template(path=TEMPLATE_PATH):
    with open(path, encoding="utf-8") as handle:
        t = json.load(handle)
    if not t.get("strategies"):
        raise DataError("템플릿에 전략이 없습니다")
    return t


def mapping_table(template):
    """계좌별 전략 한눈에 보기."""
    return pd.DataFrame([{"계좌": s["account"], "전략": s["code"], "규칙": s["description"],
                          "종목": ", ".join(h["name"] for h in s["holdings"] if h["ticker"] != "CASH") or "기존 보유 유지"}
                         for s in template["strategies"]])


def apply_template(holdings, strategies, versions, template):
    """(새 보유표, 새 전략표, 새 전략 이력표, 변경 내역 표)를 돌려준다."""
    h = holdings.copy()
    conf = strategies.copy()
    archived = []
    changes = []
    now = datetime.now(timezone.utc).isoformat()
    for s in template["strategies"]:
        code = s["code"]
        row = {"code": code, "account": s["account"], "description": s["description"], "dynamic": s["rule"] in ("gsm", "isa_trend"),
               "active": True, "annual_limit": 0.0, "rule": s["rule"], "params_json": json.dumps(s.get("params", {}), ensure_ascii=False),
               "version": template["version"], "effective_date": template["effective_date"], "source": template.get("source", ""),
               "change_note": template["name"], "tolerance_pct": 0.0, "fractional_us": False, "cash_reserve": 0.0}
        old = conf[conf.code.eq(code)]
        if not old.empty:
            archived.append({**old.iloc[0].to_dict(), "archived_at": now})
            for k, v in row.items():
                if k in ("tolerance_pct", "fractional_us", "cash_reserve", "annual_limit"):
                    continue
                conf.loc[old.index, k] = v if not isinstance(v, bool) else v
            changes.append({"전략": code, "항목": "전략표", "내용": f"{template['version']} 규칙으로 갱신"})
        else:
            conf = pd.concat([conf, pd.DataFrame([row])], ignore_index=True)
            changes.append({"전략": code, "항목": "전략표", "내용": "새 전략 추가"})
        mine = h.strategy.eq(code)
        if mine.any() and (h.loc[mine, "account"] != s["account"]).any():
            h.loc[mine, "account"] = s["account"]
            changes.append({"전략": code, "항목": "계좌", "내용": f"계좌명을 {s['account']}(으)로"})
        listed = set()
        for item in s["holdings"]:
            ticker = str(item["ticker"]).upper()
            listed.add(ticker)
            hit = h.strategy.eq(code) & h.ticker.eq(ticker)
            if hit.any():
                for k in ("name", "market", "category", "role"):
                    h.loc[hit, k] = item[k]
                if item.get("target_pct") is not None:
                    h.loc[hit, "target_pct"] = float(item["target_pct"])
            else:
                h = pd.concat([h, pd.DataFrame([{"strategy": code, "account": s["account"], "ticker": ticker, "name": item["name"],
                                                 "market": item["market"], "category": item["category"], "role": item["role"],
                                                 "target_pct": float(item.get("target_pct") or 0), "shares": 0.0}])], ignore_index=True)
                changes.append({"전략": code, "항목": "종목 추가", "내용": f"{item['name']} ({ticker}) · 수량 0"})
        if not s.get("keep_other_holdings"):
            extra = h.strategy.eq(code) & ~h.ticker.isin(listed)
            for _, r in h[extra].iterrows():
                changes.append({"전략": code, "항목": "템플릿에 없음", "내용": f"{r['name']} ({r['ticker']}) · 목표 0%, 수량은 그대로"})
            h.loc[extra, "target_pct"] = 0.0
    codes = {s["code"] for s in template["strategies"]}
    for code in sorted(set(h.strategy) - codes):
        changes.append({"전략": code, "항목": "템플릿에 없는 전략", "내용": "그대로 둠 · 정리(매도) 후 전략 관리에서 직접 삭제"})
    h = normalize_holdings(h.reindex(columns=HOLDING_COLUMNS + [c for c in h.columns if c not in HOLDING_COLUMNS]))
    conf = normalize_strategies(conf.reindex(columns=STRATEGY_COLUMNS))
    if archived:
        versions = pd.concat([versions, pd.DataFrame(archived)], ignore_index=True)
    return h, conf, versions, pd.DataFrame(changes)
