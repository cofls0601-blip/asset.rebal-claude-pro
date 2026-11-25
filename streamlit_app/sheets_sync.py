"""Authenticated Apps Script transport; no secrets in URLs or exception messages."""
import hashlib
import json
import math
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
        raise SheetsError(errors.get(data.get('error'),'Sheets 작업 실패: '+str(data.get('error','unknown')))+where(data.get('detail')))
    return data


KINDS={'number':'숫자','text':'글자','boolean':'참/거짓','empty':'빈칸'}


def where(detail):
    """Readable location from the Apps Script (2026-11-25 version); older scripts send none."""
    if not isinstance(detail,dict):return ''
    stage=detail.get('stage')
    if stage=='write':return f" (시트에 쓰는 중 오류: {detail.get('message','알 수 없음')})"
    if stage=='read':return f" (저장 후 시트를 읽는 중 오류: {detail.get('message','알 수 없음')})"
    if detail.get('problem')=='header':return f" ({detail.get('table')} 탭의 머리글이 저장 후 달라졌습니다)"
    if detail.get('problem')=='row_count':return f" ({detail.get('table')} 탭: 보낸 줄 {detail.get('sent_rows')}개, 시트 줄 {detail.get('sheet_rows')}개)"
    if detail.get('table'):
        return f" ({detail['table']} 탭 {detail.get('row')}번째 줄 「{detail.get('column')}」 칸이 저장 후 달라졌습니다 · 보낸 값 {KINDS.get(detail.get('sent'),'?')}, 시트 값 {KINDS.get(detail.get('sheet'),'?')})"
    return ''


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


def cell_text(value):
    """The exact text a cell holds. The Apps Script formats every ledger cell as plain text, so the sheet
    gives numbers and TRUE/FALSE back as text; it then compares that with what was sent and rolls the save
    back on any difference ('save_failed_retry'). Sending text it will store unchanged avoids that."""
    if value is None or (isinstance(value,float) and math.isnan(value)):return ''
    if isinstance(value,bool):return 'TRUE' if value else 'FALSE'
    if isinstance(value,float):return str(int(value)) if value.is_integer() and abs(value)<1e15 else f'{value:.12g}'
    return str(value)


NUMBER=re.compile(r'-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][-+]?[0-9]+)?')


def cell_key(value):
    """Same meaning → same key, as the Apps Script compares: 70, 70.0, '70' → '70'; True, 'TRUE' → 'TRUE'.
    Text with a leading zero ('005930') stays text."""
    text=cell_text(value)
    if text.upper() in ('TRUE','FALSE'):return text.upper()
    if NUMBER.fullmatch(text):return cell_text(float(f'{float(text):.12g}'))
    return text


def save_workspace(url,secret,workspace,token,*,transport=None):
    if not token:raise SheetsError('저장하기 전에 Sheets 원장을 읽어야 합니다')
    payload=json.loads(backup_bytes(workspace))
    payload.pop('drafts',None)
    payload['tables']={k:[{c:cell_text(v) for c,v in row.items()} for row in rows] for k,rows in payload['tables'].items()}
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
        # Compare cell texts: loading turns some text back into numbers/booleans, others stay text.
        expected=workspace[key].reset_index(drop=True).astype(object).map(cell_key)
        actual=saved[key].reset_index(drop=True).astype(object).map(cell_key)
        if list(expected.columns)!=list(actual.columns) or not expected.equals(actual):
            raise SheetsError('저장 후 '+key+' 내용이 일치하지 않습니다. 원본 백업을 보존하세요')
    return observed_token

