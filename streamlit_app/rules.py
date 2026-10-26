"""Strategy-specific monthly checks (docs/전략 명세.md).

Only LAA, GSM, SSO and ISA are judged. Results are proposals: targets are
strategy-internal weights (%) that the user may apply; nothing is applied here.
"""
from datetime import timedelta
import math
import pandas as pd
from streamlit_app.data import DataError
from streamlit_app.manual import clean

ORDER=['GSM','LAA','SSO','ISA']
QUARTER_MONTHS=(3,6,9,12)
# Same staged weights as the spec: (drawdown threshold %, risk-asset weight %).
LADDERS={
    'SSO':dict(signal='SPY',base=70.,steps=[(-15.,85.),(-20.,92.5)],keyword='SSO'),
    'ISA':dict(signal='QQQ',base=0.,steps=[(-10.,100/3),(-15.,200/3),(-20.,100.)],keyword='레버리지'),
}
GSM_INVEST=80.
# A step counts as already executed when the risk weight is within this many %p of it,
# so price drift after buying does not trigger the same purchase again.
STEP_TOLERANCE=5.
LAA_FILTER_WORDS=('나스닥','NASDAQ','유로','EURO')


def decision(code,status,headline,evidence=None,targets=None,current=None,notes=None):
    changed=targets is not None and current is not None and any(abs(targets[t]-current.get(t,0.))>.005 for t in targets)
    return dict(code=code,status=status,headline=headline,evidence=evidence or [],targets=targets,current=current,changed=changed,notes=notes or [])


def drawdown(series,day):
    """Latest close versus the highest close of the last 52 weeks (%)."""
    year=series[series.index>pd.Timestamp(day)-timedelta(days=365)]
    if len(year)<200:raise DataError('52주 고점 계산에 필요한 가격이 부족합니다')
    high=float(year.max());close=float(year.iloc[-1])
    return close/high*100-100,close,high


def current_weights(sub):
    if sub.weight.isna().any():raise DataError('종가를 모두 조회해야 판정할 수 있습니다')
    return {r.ticker:float(r.weight) for r in sub.itertuples()}


def check_gsm(sub,day,fetch):
    current=current_weights(sub);rows=sub[sub.ticker.ne('CASH')]
    if rows.empty:raise DataError('후보 종목이 없습니다')
    if rows[['close','sma10','return12']].isna().any().any():raise DataError('후보의 SMA·12개월 수익률 자료가 부족합니다')
    evidence=[{'종목':r.name,'종가':round(r.close,2),'10개월 SMA':round(r.sma10,2),'12개월(%)':round(r.return12,2),'판정':'SMA 위' if r.close>r.sma10 else 'SMA 아래'} for r in rows.itertuples()]
    passed=rows[rows.close>rows.sma10]
    targets={t:0. for t in current}
    if 'CASH' not in targets:raise DataError('CASH 행이 필요합니다')
    if passed.empty:
        targets['CASH']=100.
        return decision('GSM','판정','모든 후보가 10개월 SMA 아래 → 현금 100%',evidence,targets,current)
    winner=passed.sort_values(['return12','ticker'],ascending=[False,True]).iloc[0]
    targets[winner.ticker]=GSM_INVEST;targets['CASH']=100-GSM_INVEST
    return decision('GSM','판정',f'{winner["name"]} 선택 (12개월 {winner.return12:+.2f}%) → {GSM_INVEST:g}% 투자 · 현금 {100-GSM_INVEST:g}%',evidence,targets,current)


def laa_filters(sub):
    marked=sub[sub.role.eq('필터')]
    if not marked.empty:return marked
    names=sub.name.str.upper()
    return sub[sub.ticker.ne('CASH')&names.apply(lambda n:any(w in n for w in LAA_FILTER_WORDS))]


def check_laa(sub,day,fetch):
    current=current_weights(sub)
    if 'CASH' not in current:raise DataError('CASH 행이 필요합니다')
    filters=laa_filters(sub)
    if filters.empty:raise DataError('필터 종목(나스닥·유로)을 찾지 못했습니다. 설정에서 역할을 "필터"로 지정하세요')
    if filters[['close','sma10']].isna().any().any():raise DataError('필터 종목의 SMA 자료가 부족합니다')
    below=set(filters.loc[filters.close<filters.sma10,'ticker'])
    evidence=[{'종목':r.name,'종가':round(r.close,2),'10개월 SMA':round(r.sma10,2),'판정':'SMA 아래' if r.ticker in below else 'SMA 위'} for r in filters.itertuples()]
    quarter=day.month in QUARTER_MONTHS
    if quarter:
        base={r.ticker:float(r.target_pct) for r in sub.itertuples()}
        if abs(sum(base.values())-100)>.01:raise DataError('분기 복원에 쓸 목표 비중 합계가 100%가 아닙니다')
    else:base=dict(current)
    targets=dict(base)
    for t in below:targets['CASH']+=targets[t];targets[t]=0.
    names=', '.join(sub.loc[sub.ticker.isin(below),'name']) or '없음'
    if quarter:headline=f'분기 말 목표 비중 복원 · SMA 아래 종목({names})은 현금'
    elif below:headline=f'SMA 아래: {names} → 해당 비중 현금 이동 · 나머지 유지'
    else:headline='필터 종목 모두 SMA 위 → 유지 (비중 복원은 분기 말에만)'
    return decision('LAA','판정',headline,evidence,targets,current)


def ladder_asset(code,sub):
    rows=sub[sub.ticker.ne('CASH')]
    if len(rows)>1:rows=rows[rows.role.eq('레버리지')|rows.ticker.eq(LADDERS[code]['keyword'])|rows.name.str.contains(LADDERS[code]['keyword'],regex=False)]
    if len(rows)!=1:raise DataError('투자할 종목을 하나로 정할 수 없습니다. 설정에서 역할을 "레버리지"로 지정하세요')
    return rows.iloc[0]


def check_ladder(code,sub,day,fetch):
    spec=LADDERS[code];current=current_weights(sub)
    if 'CASH' not in current:raise DataError('CASH 행이 필요합니다')
    asset=ladder_asset(code,sub);dd,close,high=drawdown(clean(fetch(spec['signal'],'US',day),day),day)
    weight=current[asset.ticker];reached=[w for limit,w in spec['steps'] if dd<=limit]
    evidence=[{'기준':spec['signal'],'종가':round(close,2),'52주 고점':round(high,2),'하락률(%)':round(dd,2),'현재 비중(%)':round(weight,2)}]
    def plan(w):
        t={k:0. for k in current};t[asset.ticker]=w;t['CASH']=100-w;return t
    if dd>=0:
        return decision(code,'판정',f'{spec["signal"]} 52주 고점 회복 → 기본 비중 {asset["name"]} {spec["base"]:g}% 복원',evidence,plan(spec['base']),current)
    if reached:
        step=len(reached);target=max(reached)
        if weight<target-STEP_TOLERANCE:
            return decision(code,'판정',f'{spec["signal"]} {dd:.1f}% → {step}단계: {asset["name"]} {target:.1f}%까지 매수',evidence,plan(target),current)
        return decision(code,'판정',f'{spec["signal"]} {dd:.1f}% → {step}단계 이미 실행됨 · 유지',evidence,dict(current),current)
    return decision(code,'판정',f'{spec["signal"]} {dd:.1f}% → 트리거 없음 · 유지',evidence,dict(current),current)


def evaluate(view,day,fetch):
    """Return one decision per strategy, judged strategies first in checklist order."""
    out=[]
    for code,sub in view.groupby('strategy',sort=False):
        if code not in ORDER:
            out.append(decision(code,'판정 없음','규칙 판정 대상이 아닙니다 · 보유'));continue
        try:
            out.append(check_ladder(code,sub,day,fetch) if code in LADDERS else (check_gsm if code=='GSM' else check_laa)(sub,day,fetch))
        except Exception as e:out.append(decision(code,'계산 불가',str(e)))
    return sorted(out,key=lambda d:ORDER.index(d['code']) if d['code'] in ORDER else len(ORDER))


def apply_targets(holdings,code,targets):
    """Write proposed weights into the strategy's target_pct; the caller validates."""
    if targets is None or not math.isclose(sum(targets.values()),100,abs_tol=.01):raise DataError('적용할 목표 비중이 없습니다')
    h=holdings.copy();mask=h.strategy.eq(code)
    if set(h.loc[mask,'ticker'])!=set(targets):raise DataError('종목 구성이 바뀌었습니다. 종가를 다시 조회하세요')
    h.loc[mask,'target_pct']=h.loc[mask,'ticker'].map(targets).round(4)
    return h
