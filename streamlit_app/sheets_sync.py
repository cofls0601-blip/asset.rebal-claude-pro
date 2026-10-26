"""Authenticated Apps Script transport; no secrets in URLs or exception messages."""
import hashlib
import json
import re
import requests
from streamlit_app.data import DataError
from streamlit_app.ledger import TABLES, backup_bytes, restore_backup, empty_workspace


class SheetsError(DataError):
    pass


def request(url, secret, action, *, transport=None, **payload):
    if not re.fullmatch(r'https://script\.google\.com/macros/s/[A-Za-z0-9_-]+/exec',url or ''):
        raise SheetsError('SHEETS_WEBAPP_URL은 배포된 Apps Script /exec URL이어야 합니다')
    if not secret or len(secret)<24:
        raise SheetsError('SHEETS_SECRET은 24자 이상의 임의 문자열이어야 합니다')
    try:
        response=(transport or requests).post(url,json={'secret':secret,'action':action,**payload},timeout=(10,60))
        response.raise_for_status()
        data=response.json()
    except (requests.RequestException,ValueError) as exc:
        raise SheetsError('Sheets 응답을 확인하지 못했습니다. 세션 자료는 유지됩니다. 연결·배포 권한을 확인한 뒤 재시도하세요') from exc
    if not isinstance(data,dict):raise SheetsError('Sheets 응답 형식이 올바르지 않습니다')
    if not data.get('ok'):
        errors={'unauthorized':'Sheets 시크릿이 일치하지 않습니다',
            'conflict':'다른 세션 또는 시트에서 자료가 바뀌었습니다. 현재 작업을 백업하고 최신 시트를 다시 읽어 병합하세요',
            'busy':'다른 저장이 진행 중입니다. 잠시 후 다시 저장하세요',
            'save_failed_retry':'저장 완료를 확인하지 못했습니다. 같은 작업을 재시도하세요',
            'recovery_required':'이전 저장 복구에 실패했습니다. 시트를 보존하고 운영 문서의 복구 절차를 확인하세요'}
        raise SheetsError(errors.get(data.get('error'),'Sheets 작업 실패: '+str(data.get('error','unknown'))))
    return data


def load_workspace(url,secret,*,transport=None):
    data=request(url,secret,'load',transport=transport)
    if not data.get('token'):raise SheetsError('서버가 버전 정보를 반환하지 않았습니다')
    payload=data.get('workspace')
    if payload is None:raise SheetsError('서버가 원장을 반환하지 않았습니다')
    # Empty/new tabs have no header until the first explicit save.
    defaults=empty_workspace()
    for k in TABLES:
        if not payload.get('columns',{}).get(k) and not payload.get('tables',{}).get(k):
            payload.setdefault('columns',{})[k]=list(defaults[k].columns)
    workspace=restore_backup(json.dumps(payload,ensure_ascii=False).encode())
    return workspace,data['token']


def save_workspace(url,secret,workspace,token,*,transport=None):
    if not token:raise SheetsError('저장하기 전에 Sheets 원장을 읽어야 합니다')
    payload=json.loads(backup_bytes(workspace))
    payload.pop('drafts',None)
    encoded=json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':'))
    if len(encoded.encode())>5_000_000:raise SheetsError('한 번에 5MB까지 저장할 수 있습니다. 전체 백업으로 기록을 보존하세요')
    request_id=hashlib.sha256((token+encoded).encode()).hexdigest()
    result=request(url,secret,'save',workspace=payload,expected_token=token,request_id=request_id,transport=transport)
    if not result.get('token') or result.get('request_id')!=request_id:
        raise SheetsError('저장 확인 정보가 일치하지 않습니다. 같은 작업을 재시도하세요')
    # Read-after-write catches incomplete writes or intervening manual edits.
    saved,observed_token=load_workspace(url,secret,transport=transport)
    if observed_token!=result['token']:
        raise SheetsError('저장 후 시트가 다시 변경되었습니다. 현재 작업을 백업하고 최신 자료를 읽으세요')
    for key in TABLES:
        expected=workspace[key].fillna('').astype(str)
        actual=saved[key].fillna('').astype(str)
        # Numeric type normalization may turn 1 into 1.0; compare canonical JSON via pandas.
        try:
            import pandas as pd
            pd.testing.assert_frame_equal(workspace[key].reset_index(drop=True),saved[key].reset_index(drop=True),check_dtype=False,check_index_type=False,check_exact=False)
        except AssertionError:
            if not expected.equals(actual):raise SheetsError('저장 후 '+key+' 내용이 일치하지 않습니다. 원본 백업을 보존하세요')
    return observed_token

