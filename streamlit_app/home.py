"""Home screen parts (design 2.0): account list with expandable detail, asset-class card, monthly record data."""
from html import escape
import pandas as pd
from streamlit_app import ui
from streamlit_app.manual import GOLD_TICKER


def account_status(code,judged,check):
    """Small gray text next to the code chip: what the app does with this account."""
    issues=check['issues'] if check else []
    bad=sum(l=='문제' for l,_ in issues);warn=sum(l=='확인' for l,_ in issues)
    if bad:return ui.tag(f'문제 {bad}','bad')
    if warn:return ui.tag(f'확인 {warn}','warn')
    if judged:return '판정함'
    if code=='KSP':return '2027부터'
    if code=='GOLD':return '국제시세 추정'
    if code in ('CASH','RESERVE'):return '판정 제외'
    return '보유만'


def account_detail(sub):
    """Target vs current asset-class donuts, then one bar per holding (current vs target)."""
    cats=[c for c in ui.ASSET_ORDER if c in set(sub.category)]+[c for c in dict.fromkeys(sub.category) if c not in ui.ASSET_ORDER]
    target=sub.groupby('category').target_pct.sum();current=sub.groupby('category').weight.sum()
    donuts=(f'<div class="ds-donuts">{ui.donut([(c,target.get(c,0),ui.asset_color(c)) for c in cats],"목표")}'
            f'{ui.donut([(c,current.get(c,0),ui.asset_color(c)) for c in cats],"현재")}</div>')
    rows=''
    for r in sub.itertuples():
        shares='' if r.ticker=='CASH' else f'{r.shares:,.4f}'.rstrip('0').rstrip('.')+('g · ' if r.ticker==GOLD_TICKER else '주 · ')
        rows+=ui.bar_row(r.name,shares+ui.won(r.value),r.weight,r.target_pct,ui.asset_color(r.category))
    head='<div class="ds-bar-head ds-label" style="margin-top:10px"><span>종목 · 평가액</span><span>현재 / 목표</span></div>'
    return donuts+ui.legend([(c,ui.asset_color(c)) for c in cats])+head+rows


def account_list(view,judged,checks,day_change):
    """One collapsible row per strategy: dot, account name, code chip + status, value and day change."""
    rows=''
    for code,sub in view.groupby('strategy',sort=False):
        value=sub.value.sum() if sub.value.notna().all() else None
        name=str(sub.account.iloc[0])
        if code=='GOLD' and (sub.ticker==GOLD_TICKER).any():
            grams=float(sub.loc[sub.ticker.eq(GOLD_TICKER),'shares'].sum());name=f'{name} {grams:,g}g' if grams else name
        rows+=(f'<details><summary><span class="ds-dot" style="background:{ui.strategy_color(code)}"></span>'
               f'<span class="ds-acct-name"><b>{escape(name)}</b><small>{ui.chip(code)} {account_status(code,judged.get(code),checks.get(code))}</small></span>'
               f'<span class="ds-acct-val"><b>{ui.won(value,unit=False)}</b>{ui.pct_change(day_change.get(code))}</span></summary>'
               f'<div class="ds-acct-body">{account_detail(sub)}</div></details>')
    return f'<div class="ds-acct">{rows}</div>'


def asset_card(view):
    total=view.value.sum()
    shares=view.groupby('category').value.sum()/total*100 if total else pd.Series(dtype=float)
    cats=sorted(shares.index,key=lambda c:-shares[c])
    ring=ui.donut([(c,shares[c],ui.asset_color(c)) for c in ui.ASSET_ORDER+[c for c in cats if c not in ui.ASSET_ORDER] if c in shares],f'{len(cats)}개',size=132)
    items=''.join(f'<li><span><i style="background:{ui.asset_color(c)}"></i>{escape(c)}</span><b>{shares[c]:.0f}%</b></li>' for c in cats)
    return f'<div class="ds-assets">{ring}<ul>{items}</ul></div>'


def monthly(snapshots,by='strategy'):
    """Month-end totals per strategy (or asset class) from 월별 기록: latest record date in each month, latest revision."""
    if snapshots is None or snapshots.empty or 'value' not in snapshots:return pd.DataFrame(columns=['month','date','key','account','value'])
    s=snapshots.copy();s['date']=pd.to_datetime(s.date,errors='coerce');s['value']=pd.to_numeric(s.value,errors='coerce')
    s=s[s.date.notna()&s.value.notna()]
    if s.empty:return pd.DataFrame(columns=['month','date','key','account','value'])
    s['month']=s.date.dt.to_period('M')
    s=s[s.date.eq(s.groupby('month').date.transform('max'))]
    if 'revision' in s:
        s['rev']=pd.to_numeric(s.revision,errors='coerce').fillna(1);s=s[s.rev.eq(s.groupby('month').rev.transform('max'))]
    key='strategy' if by=='strategy' else 'category'
    acct=s.groupby('strategy').account.last() if 'account' in s else pd.Series(dtype=str)
    out=s.groupby(['month','date',key],as_index=False).value.sum().rename(columns={key:'key'})
    out['account']=out.key.map(acct).fillna(out.key) if by=='strategy' else out.key
    return out.sort_values(['month','key']).reset_index(drop=True)


def todo_kind(decision):
    """Two-word summary of a proposal for the home to-do card: 사고팔기 / 매수 / 매도."""
    cur=decision.get('current') or {};tgt=decision.get('targets') or {}
    up=[t for t in tgt if t!='CASH' and tgt[t]>cur.get(t,0)+.5];down=[t for t in tgt if t!='CASH' and tgt[t]<cur.get(t,0)-.5]
    return '사고팔기' if up and down else '매수' if up else '매도' if down else '비중 맞추기'


def expected_weights(sub_view,shares):
    """Weight (%) of each holding in its account if the quantities were `shares` {ticker: qty},
    priced at the loaded quotes (CASH counts in won). None when a price is missing."""
    values={}
    for r in sub_view.itertuples():
        q=float(shares.get(r.ticker,r.shares))
        if r.ticker=='CASH':values[r.ticker]=q;continue
        if pd.isna(r.close) or pd.isna(r.fx):return None
        values[r.ticker]=q*float(r.close)*float(r.fx)
    total=sum(values.values())
    return {t:(v/total*100 if total else 0.) for t,v in values.items()},total
