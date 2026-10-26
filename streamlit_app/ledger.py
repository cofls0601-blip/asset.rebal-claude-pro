import json
import io
import pandas as pd
from streamlit_app.data import *
SCHEMA_VERSION = 3
TABLES = ['holdings','strategies','snapshots','actions','cashflows','category_targets','evaluations','strategy_versions']
SCHEMAS = dict(zip(TABLES, [HOLDING_COLUMNS, STRATEGY_COLUMNS,
    SNAPSHOT_COLUMNS + ['schema_version','run_id','record_id','revision','revision_reason','role','fx','account_weight_pct','execution_target_pct','price_date','fx_date','price_source','strategy_json','classification_json'],
    ACTION_COLUMNS + ['schema_version','execution_id','order_id','run_id','execution_date','actual_price','fx','actual_amount','currency','status'],
    CASHFLOW_COLUMNS + ['kind','transfer_id'], CATEGORY_TARGET_COLUMNS,
    ['run_id','date','engine_version','part','parts','payload_json'], STRATEGY_COLUMNS + ['archived_at']]))


def empty_workspace():
    return {k:pd.DataFrame(columns=SCHEMAS[k]) for k in TABLES}

def records(frame):
    return json.loads(frame.to_json(orient='records',date_format='iso',force_ascii=False))

def backup_bytes(workspace,drafts=None):
    return json.dumps({'schema_version':3,'tables':{k:records(workspace[k]) for k in TABLES},'columns':{k:list(workspace[k].columns) for k in TABLES},'drafts':drafts or {}},ensure_ascii=False,allow_nan=False).encode()

def restore_backup(raw):
    try:
        p=json.loads(raw)
        if p['schema_version']!=3:raise DataError('지원하지 않는 백업 버전입니다')
        w={k:pd.DataFrame(p['tables'][k],columns=p.get('columns',{}).get(k,SCHEMAS[k])) for k in TABLES}
        w['holdings']=normalize_holdings(w['holdings']);w['strategies']=normalize_strategies(w['strategies'])
        return w
    except (ValueError,KeyError,TypeError) as exc:raise DataError('올바른 전체 백업 JSON이 아닙니다') from exc

def parse_table(raw):
    return pd.read_csv(io.StringIO(raw.decode('utf-8-sig') if isinstance(raw,bytes) else raw),sep=None,engine='python',dtype={'ticker':str})
