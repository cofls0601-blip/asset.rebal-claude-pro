"""Strategy-specific monthly checks (docs/전략 명세.md).

Only GSM, DAA, LAA, SSO, ISA and EM are judged. Results are proposals: targets are
strategy-internal weights (%) that the user may apply; nothing is applied here.
Rule options come from the strategy table's params_json (2027 rules, docs/2027 운용 안내.md):
  GSM {"top": 2, "cash": "153130"}   top-N candidates; the cash share goes to the cash ticker
  DAA {...}                          Keller DAA, domestic-ETF version (see check_daa)
  ISA {"mode": "trend", "signal": "SPY", "cash": "153130"}  signal above 10-month SMA → leverage 100%, else cash
  EM  {"max_pct": 30, "month": 12}   yearly check that no holding exceeds max_pct (2026~)
  EM  {"mode": "kr_half", ...}       Korean stocks 50% with the half filter + S&P500 50% (see check_kr_half)
"cash" is the ticker that holds the cash share (e.g. KODEX 단기채권); without it the CASH row is used.
"""
from datetime import timedelta
import json
import math
import pandas as pd
from streamlit_app.data import DataError
from streamlit_app.manual import clean

ORDER=['GSM','DAA','LAA','SSO','ISA','EM']
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


def cash_of(sub,params):
    """Ticker that holds the cash share: params['cash'] when it is in the strategy, else the CASH row."""
    c=str((params or {}).get('cash','CASH')).upper()
    if c!='CASH' and c in set(sub.ticker):return c
    if 'CASH' not in set(sub.ticker):raise DataError('CASH 행이 필요합니다')
    return 'CASH'


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


def monthly_trend(series,day):
    """Close and 10-month SMA where the chosen day's close is this month's month-end close."""
    s=series[series.index<=pd.Timestamp(day)]
    months=s.resample('ME').last().dropna()
    if len(months)<10:raise DataError('10개월 SMA 계산에 필요한 가격이 부족합니다')
    return float(months.iloc[-1]),float(months.tail(10).mean())


def check_gsm(sub,day,fetch,params=None):
    current=current_weights(sub);cash=cash_of(sub,params);rows=sub[~sub.ticker.isin(['CASH',cash])]
    if rows.empty:raise DataError('후보 종목이 없습니다')
    if rows[['close','sma10','return12']].isna().any().any():raise DataError('후보의 SMA·12개월 수익률 자료가 부족합니다')
    evidence=[{'종목':r.name,'종가':round(r.close,2),'10개월 SMA':round(r.sma10,2),'12개월(%)':round(r.return12,2),'판정':'SMA 위' if r.close>r.sma10 else 'SMA 아래'} for r in rows.itertuples()]
    passed=rows[rows.close>rows.sma10]
    targets={t:0. for t in current}
    cash_name='현금' if cash=='CASH' else str(sub.loc[sub.ticker.eq(cash),'name'].iloc[0])
    if passed.empty:
        targets[cash]=100.
        return decision('GSM','판정',f'모든 후보가 10개월 SMA 아래 → {cash_name} 100%',evidence,targets,current)
    top=max(1,int((params or {}).get('top',1)))
    winners=passed.sort_values(['return12','ticker'],ascending=[False,True]).head(top)
    for t in winners.ticker:targets[t]=GSM_INVEST/len(winners)
    targets[cash]=100-GSM_INVEST
    picked=', '.join(f'{w["name"]} (12개월 {w.return12:+.2f}%)' for _,w in winners.iterrows())
    split=f'{GSM_INVEST:g}% 투자' if len(winners)==1 else f'각 {GSM_INVEST/len(winners):g}% 투자'
    return decision('GSM','판정',f'{picked} 선택 → {split} · {cash_name} {100-GSM_INVEST:g}%',evidence,targets,current)


def laa_filters(sub):
    marked=sub[sub.role.eq('필터')]
    if not marked.empty:return marked
    names=sub.name.str.upper()
    return sub[sub.ticker.ne('CASH')&names.apply(lambda n:any(w in n for w in LAA_FILTER_WORDS))]


def check_laa(sub,day,fetch,params=None):
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


def ladder_asset(code,sub,cash='CASH'):
    rows=sub[~sub.ticker.isin(['CASH',cash])]
    if len(rows)>1:rows=rows[rows.role.eq('레버리지')|rows.ticker.eq(LADDERS[code]['keyword'])|rows.name.str.contains(LADDERS[code]['keyword'],regex=False)]
    if len(rows)!=1:raise DataError('투자할 종목을 하나로 정할 수 없습니다. 설정에서 역할을 "레버리지"로 지정하세요')
    return rows.iloc[0]


def check_trend(code,sub,day,fetch,params):
    """2027 ISA: signal ETF above its 10-month SMA → leverage 100%, otherwise cash 100%."""
    signal=params.get('signal','QQQ');current=current_weights(sub);cash=cash_of(sub,params)
    asset=ladder_asset(code,sub,cash);close,sma=monthly_trend(clean(fetch(signal,'US',day),day),day)
    above=close>sma;weight=current[asset.ticker]
    evidence=[{'기준':signal,'종가':round(close,2),'10개월 SMA':round(sma,2),'판정':'SMA 위' if above else 'SMA 아래','현재 비중(%)':round(weight,2)}]
    targets={k:0. for k in current};targets[cash]=0. if above else 100.
    if above:targets[asset.ticker]=100.
    cash_name='현금' if cash=='CASH' else str(sub.loc[sub.ticker.eq(cash),'name'].iloc[0])
    headline=f'{signal} SMA 위 → {asset["name"]} 100%' if above else f'{signal} SMA 아래 → {cash_name} 100%'
    return decision(code,'판정',headline,evidence,targets,current)


def check_cap(code,sub,day,fetch,params):
    """Yearly single-holding cap: trim anything above max_pct of the account into cash."""
    limit=float(params.get('max_pct',30));month=int(params.get('month',12))
    if day.month!=month:return decision(code,'판정 없음',f'한 종목 {limit:g}% 상한은 매년 {month}월에 점검합니다 · 보유')
    current=current_weights(sub)
    if 'CASH' not in current:raise DataError('CASH 행이 필요합니다')
    over={t:w for t,w in current.items() if t!='CASH' and w>limit}
    names=dict(zip(sub.ticker,sub.name))
    evidence=[{'종목':names.get(t,t),'현재 비중(%)':round(w,2),'판정':'상한 초과' if t in over else '상한 이내'} for t,w in current.items() if t!='CASH']
    if not over:return decision(code,'판정',f'모든 종목이 계좌의 {limit:g}% 이하 → 유지',evidence,dict(current),current)
    targets=dict(current)
    for t,w in over.items():targets[t]=limit;targets['CASH']+=w-limit
    return decision(code,'판정',f'{", ".join(names.get(t,t) for t in over)} {limit:g}% 초과 → 넘는 만큼 현금으로',evidence,targets,current)


def check_ladder(code,sub,day,fetch,params=None):
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


# ------------------------------------------------------------------ DAA (과세 연금저축, 2027)
# Domestic-ETF version backtested in backtest/evaluate.py (P["DAA"]): offense top 3 by 13612W momentum,
# canaries 신흥국(195980) and AGG (US dollar price) set the offense share to 100/50/0%, the rest goes to
# the stronger of 미국10년채 and 단기채권.
DAA_DEFAULT=dict(
    offense=['360750','133690','195970','195980','411060','308620','476760'],
    canary=[['195980','KR'],['AGG','US']],
    defense='308620',cash='153130',top=3)


def momentum_13612(series,day):
    """12×1개월 + 4×3개월 + 2×6개월 + 1×12개월 수익률 (월말 값, 기준일 종가 = 이번 달 월말)."""
    s=series[series.index<=pd.Timestamp(day)]
    months=s.resample('ME').last().dropna()
    if len(months)<13:raise DataError('13612 모멘텀 계산에 필요한 13개월 가격이 부족합니다')
    r={k:float(months.iloc[-1]/months.iloc[-1-k]-1) for k in (1,3,6,12)}
    return 12*r[1]+4*r[3]+2*r[6]+r[12],r


def adjusted(fetch,ticker,market,day):
    """Dividend-adjusted closes when the fetcher supports it (the backtest uses total-return prices)."""
    try:return fetch(ticker,market,day,adjusted=True)
    except TypeError:return fetch(ticker,market,day)


def check_daa(sub,day,fetch,params=None):
    p={**DAA_DEFAULT,**(params or {})}
    current=current_weights(sub);cash=cash_of(sub,p)
    names=dict(zip(sub.ticker,sub.name))
    offense=[str(t).upper() for t in p['offense']];defense=str(p['defense']).upper();top=int(p['top'])
    missing=[t for t in offense+[defense] if t not in current]
    if missing:raise DataError(f'보유표에 DAA 후보가 없습니다: {", ".join(missing)} (설정 → 2027 전략 템플릿 적용)')
    if cash=='CASH':raise DataError(f'방어용 단기채권({p["cash"]}) 행이 필요합니다')
    score,parts={},{}
    for t in dict.fromkeys(offense+[defense,cash]):
        score[t],parts[t]=momentum_13612(clean(adjusted(fetch,t,'KR',day),day),day)
    canary=[]
    for t,m in p['canary']:
        sc,pt=momentum_13612(clean(adjusted(fetch,str(t).upper(),m,day),day),day)
        canary.append((str(t).upper(),sc,pt))
    bad=sum(sc<=0 for _,sc,_ in canary);off=1-bad/len(canary)
    ranked=sorted(offense,key=lambda t:-score[t])  # stable: ties keep the offense order
    picks=ranked[:top]
    safe=max([defense,cash],key=lambda t:score[t])
    targets={t:0. for t in current}
    if off>0:
        for t in picks:targets[t]+=off/top*100
    if off<1:targets[safe]+=(1-off)*100
    def row(t,label,sc,pt,mark):
        return {'종목':names.get(t,t),'구분':label,'1개월(%)':round(pt[1]*100,2),'3개월(%)':round(pt[3]*100,2),
                '6개월(%)':round(pt[6]*100,2),'12개월(%)':round(pt[12]*100,2),'점수':round(sc*100,1),'판정':mark}
    evidence=[row(t,'위험 신호',sc,pt,'플러스' if sc>0 else '마이너스 → 위험') for t,sc,pt in canary]
    for i,t in enumerate(ranked,1):
        evidence.append(row(t,f'공격 후보 {i}위',score[t],parts[t],'선택' if off>0 and t in picks else ''))
    for t in dict.fromkeys([defense,cash]):
        evidence.append(row(t,'방어 후보',score[t],parts[t],'선택' if off<1 and t==safe else ''))
    on=[names.get(t,t) for t,sc,_ in canary if sc<=0]
    head=f'위험 신호 {bad}개' + (f'({", ".join(on)})' if on else '') + f' → 공격 {off*100:g}%'
    if off>0:head+=': '+'·'.join(names.get(t,t) for t in picks)+f' 각 {off/top*100:.1f}%'
    if off<1:head+=f' · {names.get(safe,safe)} {(1-off)*100:g}%'
    return decision('DAA','판정',head,evidence,targets,current)


# ------------------------------------------------------------------ 일반계좌 1 (2027): 국내 주식 50% 절반 필터 + S&P500 50%
KR_HALF_DEFAULT=dict(kr_share=50,signal='069500',spx='SPY',month=12,max_pct=30,start='2027-01')


def check_kr_half(code,sub,day,fetch,params=None):
    """국내 주식 kr_share% + S&P500 나머지. KODEX 200이 10개월 SMA 아래면 국내 몫의 절반을 현금으로.
    상태가 바뀐 달, 매년 month월, 시작 달에만 비중을 다시 맞춘다(그 밖의 달은 유지).
    month월에는 국내 한 종목이 국내 몫의 max_pct%를 넘으면 넘는 만큼 현금으로."""
    p={**KR_HALF_DEFAULT,**(params or {})}
    current=current_weights(sub);cash=cash_of(sub,p);spx=str(p['spx']).upper()
    if spx not in current:raise DataError(f'S&P500 종목({spx}) 행이 필요합니다')
    kr=[t for t in current if t not in ('CASH',cash,spx)]
    names=dict(zip(sub.ticker,sub.name))
    s=clean(fetch(str(p['signal']),'KR',day),day)
    months=s.resample('ME').last().dropna()
    if len(months)<11:raise DataError('신호 계산에 필요한 11개월 가격이 부족합니다')
    close,sma=float(months.iloc[-1]),float(months.tail(10).mean())
    prev_close,prev_sma=float(months.iloc[-2]),float(months.iloc[-11:-1].mean())
    below,prev_below=close<sma,prev_close<prev_sma
    yearly=day.month==int(p['month']);start=f'{day:%Y-%m}'==str(p['start'])
    evidence=[{'기준':names.get(str(p['signal']),'KODEX 200'),'종가':round(close,2),'10개월 SMA':round(sma,2),
               '판정':'SMA 아래' if below else 'SMA 위','지난달':'SMA 아래' if prev_below else 'SMA 위'}]
    state='SMA 아래 → 국내 몫 절반 현금' if below else 'SMA 위 → 국내 몫 전부 주식'
    if not (below!=prev_below or yearly or start):
        return decision(code,'판정',f'KODEX 200 {"SMA 아래" if below else "SMA 위"} 유지 → 할 일 없음',evidence,dict(current),current)
    kr_sum=sum(current[t] for t in kr)
    if not kr or kr_sum<=0:raise DataError('국내 주식 보유가 없습니다')
    share=float(p['kr_share']);stock=share*(.5 if below else 1.)
    targets={t:0. for t in current}
    cap=stock*float(p['max_pct'])/100 if yearly else None
    for t in kr:
        w=stock*current[t]/kr_sum
        targets[t]=min(w,cap) if cap is not None else w
    targets[spx]=100-share
    targets[cash]+=100-sum(targets.values())
    why=('KODEX 200 신호가 바뀜' if below!=prev_below else '')+(' · ' if below!=prev_below and (yearly or start) else '')+\
        (f'{p["month"]}월 비율 복원' if yearly else '')+('시작 달 비율 맞춤' if start and not yearly else '')
    over=[names.get(t,t) for t in kr if cap is not None and stock*current[t]/kr_sum>cap+1e-9]
    head=f'{why}: {state} · 국내 {stock:g}% · S&P500 {100-share:g}%'+(f' · 상한 초과 {", ".join(over)}' if over else '')
    return decision(code,'판정',head,evidence,targets,current)


def strategy_params(strategies):
    """{code: params dict} from the strategy table; bad or missing JSON means 2026 defaults."""
    if strategies is None or strategies.empty:return {}
    out={}
    for r in strategies.itertuples():
        try:p=json.loads(r.params_json or '{}')
        except (TypeError,ValueError):p={}
        out[str(r.code)]=p if isinstance(p,dict) else {}
    return out


def evaluate(view,day,fetch,strategies=None):
    """Return one decision per strategy, judged strategies first in checklist order."""
    out=[];params=strategy_params(strategies)
    for code,sub in view.groupby('strategy',sort=False):
        p=params.get(code,{})
        if code not in ORDER or (code=='EM' and 'max_pct' not in p and p.get('mode')!='kr_half'):
            out.append(decision(code,'판정 없음','규칙 판정 대상이 아닙니다 · 보유'));continue
        try:
            if code=='DAA':d=check_daa(sub,day,fetch,p)
            elif code=='EM' and p.get('mode')=='kr_half':d=check_kr_half(code,sub,day,fetch,p)
            elif code=='EM':d=check_cap(code,sub,day,fetch,p)
            elif code=='ISA' and p.get('mode')=='trend':d=check_trend(code,sub,day,fetch,p)
            elif code in LADDERS:d=check_ladder(code,sub,day,fetch,p)
            else:d=(check_gsm if code=='GSM' else check_laa)(sub,day,fetch,p)
            out.append(d)
        except Exception as e:out.append(decision(code,'계산 불가',str(e)))
    return sorted(out,key=lambda d:ORDER.index(d['code']) if d['code'] in ORDER else len(ORDER))


def apply_targets(holdings,code,targets):
    """Write proposed weights into the strategy's target_pct; the caller validates."""
    if targets is None or not math.isclose(sum(targets.values()),100,abs_tol=.01):raise DataError('적용할 목표 비중이 없습니다')
    h=holdings.copy();mask=h.strategy.eq(code)
    if set(h.loc[mask,'ticker'])!=set(targets):raise DataError('종목 구성이 바뀌었습니다. 종가를 다시 조회하세요')
    h.loc[mask,'target_pct']=h.loc[mask,'ticker'].map(targets).round(4)
    return h
