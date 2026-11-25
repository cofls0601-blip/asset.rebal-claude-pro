"""Account check-up: which rule each strategy gets, and what in the sheet would make it go wrong.

Pure functions so the screen and the tests share them. Levels: '문제' (orders or judgments
will be wrong), '확인' (worth a look), '정상'.
"""
import json
import math
import pandas as pd
from streamlit_app import rules
from streamlit_app.manual import GOLD_TICKER

ROLES=['','현금','필터','레버리지']  # the only role values the rules read


def params_of(strategies,code):
    if strategies is None or strategies.empty or code not in set(strategies.code):return {}
    try:p=json.loads(strategies.set_index('code').loc[code,'params_json'] or '{}')
    except (TypeError,ValueError):p={}
    return p if isinstance(p,dict) else {}


def describe(code,params):
    """The rule rules.evaluate applies to this strategy code, in one plain sentence."""
    p=params or {}
    if code=='GSM':
        top=int(p.get('top',1));return f'10개월 평균선 위 후보 중 12개월 수익률 {"1위" if top==1 else f"상위 {top}개"}에 80%, 현금 20% (모두 아래면 현금 100%)'
    if code=='DAA':return '카나리아가 모두 좋으면 공격 자산 상위 종목, 아니면 방어 자산으로 (DAA)'
    if code=='LAA':return '6자산 고정 비중, 나스닥·유로만 10개월 평균선 아래면 현금. 분기 말에 비중 복원'
    if code=='SSO':return 'SSO 70 / 현금 30. SPY가 52주 고점보다 -15%·-20% 내리면 단계적으로 더 삼'
    if code=='ISA':
        if p.get('mode')=='trend':return f'{p.get("signal","QQQ")}가 10개월 평균선 위면 레버리지 100%, 아래면 현금'
        return '현금 대기. QQQ가 52주 고점보다 -10/-15/-20% 내리면 단계적으로 레버리지 매수'
    if code in ('KSP','EM') and p.get('mode')=='kr_half':return f'국내 주식 {p.get("kr_share",50):g}% + S&P500. KODEX 200이 10개월 평균선 아래면 국내 몫 절반을 현금'
    if code=='KSP':return '지금은 보유만 · 2027 전략 템플릿을 적용하면 국내 주식 50% 절반 필터 + S&P500'
    if code=='EM':
        if 'max_pct' in p:return f'매년 {p.get("month",12)}월, 한 종목이 계좌의 {p["max_pct"]:g}%를 넘으면 넘는 만큼 줄임'
    return '규칙 없음 · 보유만 (월말 리밸런싱에 나오지 않음)'


def judged(code,params):
    p=params or {}
    if code=='KSP':return p.get('mode')=='kr_half'
    return code in rules.ORDER and not (code=='EM' and 'max_pct' not in p and p.get('mode')!='kr_half')


def check(holdings,strategies=None,view=None,gap_pct=5.):
    """One row per strategy: code, account, rule sentence, status, and the list of findings."""
    out=[]
    accounts=holdings.groupby('account').strategy.unique()
    for code,sub in holdings.groupby('strategy',sort=False):
        p=params_of(strategies,code);issues=[]
        total=float(sub.target_pct.sum())
        if not math.isclose(total,100,abs_tol=.01):issues.append(('문제',f'목표 비중 합계가 {total:g}%입니다. 100%로 맞춰야 주문 수량이 맞습니다.'))
        odd=sorted({r for r in sub.role if r not in ROLES})
        if odd:issues.append(('확인','역할 칸에 판정에 쓰지 않는 값이 있습니다: '+', '.join(f'「{r}」' for r in odd)+'. 비워 두거나 현금·필터·레버리지 중에서 고르세요.'))
        for r in sub.itertuples():
            t=str(r.ticker)
            if t.isdigit() and (len(t)!=6 or r.market!='KR'):issues.append(('문제',f'{r.name}: 국내 종목 코드는 6자리 숫자이고 시장이 KR이어야 합니다(지금 {t}, {r.market}).'))
            if t=='GC=F':issues.append(('문제',f'{r.name}: 금 현물은 g 단위 「금 현물(g)」 행({GOLD_TICKER})을 쓰세요. GC=F는 온스 가격입니다.'))
        if strategies is not None and not strategies.empty and code not in set(strategies.code):issues.append(('확인','전략표에 이 코드가 없습니다. 2026 기본 규칙으로 판정합니다.'))
        others=[c for c in accounts.get(sub.account.iloc[0],[]) if c!=code]
        if others:issues.append(('확인',f'같은 계좌 이름 「{sub.account.iloc[0]}」을 쓰는 전략이 또 있습니다: {", ".join(others)}.'))
        if view is not None:
            v=view[view.strategy.eq(code)]
            missing=v.loc[v.value.isna(),'name'].tolist()
            if missing:issues.append(('문제','가격을 불러오지 못한 종목: '+', '.join(missing)+'. 평가액과 판정이 빠집니다.'))
            elif not v.empty and math.isclose(total,100,abs_tol=.01):
                gaps=(v.weight-v.target_pct).abs()
                if gaps.max()>gap_pct:
                    worst=v.loc[gaps.idxmax()]
                    issues.append(('확인',f'목표와 실제 비중 차이가 큽니다(최대 {gaps.max():.1f}%p · {worst["name"]} 목표 {worst.target_pct:g}% / 실제 {worst.weight:.1f}%).'))
        status='문제' if any(l=='문제' for l,_ in issues) else '확인' if issues else '정상'
        out.append(dict(code=code,account=sub.account.iloc[0],rule=describe(code,p),judged=judged(code,p),status=status,issues=issues))
    order={'문제':0,'확인':1,'정상':2}
    return sorted(out,key=lambda r:order[r['status']])
