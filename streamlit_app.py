from datetime import datetime
import re
from zoneinfo import ZoneInfo
from html import escape
from pathlib import Path
import hashlib
import hmac
import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_app import manual as m
from streamlit_app import rules
from streamlit_app import checkup, home, performance, ui
import plotly.graph_objects as go
from streamlit_app.orders import apply_fill, orders_frame, plan_orders
from streamlit_app.tables import change_html, portfolio_table, weight_html
from streamlit_app.data import DataError, load_default_holdings, load_default_strategies, normalize_strategies, to_csv_bytes, to_tsv
from streamlit_app.ledger import TABLES, empty_workspace, backup_bytes, restore_backup, parse_table
from streamlit_app.sheets_sync import load_workspace, save_workspace
from streamlit_app.template import apply_template, load_template, mapping_table

APP_VERSION='2026-11-28 · 디자인 2.0 홈·월말 리밸런싱'
st.set_page_config(page_title='Rebalance · 자산배분',page_icon='◈',layout='wide')
st.markdown('<style>'+Path(__file__).with_name('streamlit_app').joinpath('theme.css').read_text()+'</style>',unsafe_allow_html=True)

def settings():
    try:return {k:str(st.secrets.get(k,'')) for k in ['SHEETS_WEBAPP_URL','SHEETS_SECRET','APP_PASSWORD']}
    except FileNotFoundError:return {}
remote=settings();connected=bool(remote.get('SHEETS_WEBAPP_URL'))
if connected:
    if len(remote.get('APP_PASSWORD',''))<12:st.error('APP_PASSWORD를 12자 이상 설정하세요.');st.stop()
    version=hashlib.sha256(remote['APP_PASSWORD'].encode()).hexdigest()
    if st.session_state.get('auth')!=version:
        st.title('자산배분 작업 공간')
        with st.form('login'):
            password=st.text_input('앱 비밀번호',type='password')
            if st.form_submit_button('열기'):
                if hmac.compare_digest(password.encode(),remote['APP_PASSWORD'].encode()):st.session_state.auth=version;st.rerun()
                else:st.error('비밀번호를 확인하세요.')
        st.stop()

def ws():return {k:st.session_state[k] for k in TABLES}
def install(data):
    for k,v in data.items():st.session_state[k]=v
    st.session_state.pop('valued',None);st.session_state.dirty=True
    st.session_state.revision=st.session_state.get('revision',0)+1

def saved_note(error):
    """What happened to Sheets after an edit, as a short sentence for the notice."""
    if error:return f' Sheets 저장 실패: {error}'
    return ' Sheets에 저장했습니다.' if connected and not st.session_state.demo else ''

def apply(data,message,save=True):
    """Install an edit and save it to Sheets right away (save=False when the user should check first)."""
    install(data);error=None
    if save:
        with st.spinner('Sheets에 저장하는 중…'):error=persist()
    elif connected:message+=' 확인한 뒤 사이드바의 「Sheets에 저장」을 누르세요.'
    st.session_state['notice_error' if error else 'notice']=message+(saved_note(error) if save else '');st.rerun()

if 'holdings' not in st.session_state:
    install(empty_workspace());st.session_state.holdings=load_default_holdings();st.session_state.strategies=normalize_strategies(load_default_strategies())
    st.session_state.demo=True;st.session_state.dirty=False
if connected and not st.session_state.get('loaded'):
    try:
        data,token=load_workspace(remote['SHEETS_WEBAPP_URL'],remote['SHEETS_SECRET'])
        if any(not x.empty for x in data.values()):install(data);st.session_state.demo=False
        st.session_state.token=token;st.session_state.loaded=True;st.session_state.dirty=False
    except DataError as e:st.error(str(e));st.button('원장 다시 읽기');st.stop()

@st.cache_data(ttl=900,show_spinner=False)
def prices(t,market,day,adjusted=False):
    return m.fetch_prices(t,market,day,adjusted=True) if adjusted else m.fetch_prices(t,market,day)
def find(query,market,mode):return m.search(query,market,mode)

def refresh(day):
    v,errors=m.valuation(st.session_state.holdings,day,prices)
    st.session_state.valued={'date':str(day),'view':v,'errors':errors}

def price_columns(columns):
    return {c:st.column_config.NumberColumn(format='localized') for c in columns
            if c in ['종가','10개월 SMA','close','sma10','actual_price','평가액','value','actual_amount','planned_amount']}

def persist():
    """Save to Sheets when connected; returns an error message or None."""
    if not connected or st.session_state.demo:return None
    try:
        st.session_state.token=save_workspace(remote['SHEETS_WEBAPP_URL'],remote['SHEETS_SECRET'],ws(),st.session_state.token);st.session_state.dirty=False
        st.session_state.last_saved=datetime.now(ZoneInfo('Asia/Seoul'))
    except DataError as e:return str(e)

def snapshot_table(view,day,memo):
    if view.value.isna().any():raise DataError('모든 종가·환율 조회를 완료하세요')
    old=st.session_state.snapshots;same=old.date.astype(str).eq(str(day))
    revisions=pd.to_numeric(old.get('revision',pd.Series(1,index=old.index)),errors='coerce').fillna(1)
    revision=int(revisions[same].max())+1 if same.any() else 1
    new=pd.DataFrame(dict(date=str(day),saved_at=pd.Timestamp.now(tz='UTC').isoformat(),strategy=view.strategy,account=view.account,ticker=view.ticker,name=view.name,category=view.category,close=view.close,shares=view.shares,value=view.value,weight_pct=view.total_weight,target_pct=view.target_pct,strategy_version='manual',memo=memo,revision=revision,fx=view.fx,price_date=view.price_date,account_weight_pct=view.weight))
    return pd.concat([old,new],ignore_index=True)

def table(frame):
    st.dataframe(frame,hide_index=True,use_container_width=True,column_config=price_columns(frame.columns))
def picker(key):
    market=st.selectbox('시장',['KR','US'],format_func=lambda x:'한국 · 원화' if x=='KR' else '미국 · 달러',key=key+'market')
    mode=st.radio('검색 방식',['티커','종목명'],horizontal=True,key=key+'mode')
    query=st.text_input('티커 또는 종목명 검색',placeholder='예: 360750, TIGER, QQQ',key=key+'query')
    cachekey=(query.strip(),market,mode)
    if st.button('종목 검색',key=key+'search'):
        try:
            with st.spinner('종목을 검색합니다…'):results=find(query,market,'ticker' if mode=='티커' else 'name') if query.strip() else []
            st.session_state[key+'hits']=(cachekey,results)
            st.session_state[key+'choice']=0 if results else -1
            if not results:st.info('검색 결과가 없습니다. 아래에서 티커와 종목명을 직접 입력하세요.')
        except DataError as e:st.error(str(e));st.session_state[key+'hits']=(cachekey,[])
        except Exception:st.error('검색 서비스에 연결하지 못했습니다. 아래에서 직접 입력하세요.');st.session_state[key+'hits']=(cachekey,[])
    saved=st.session_state.get(key+'hits');results=saved[1] if saved and saved[0]==cachekey else []
    choice=st.selectbox('검색 결과',list(range(len(results)))+[-1],format_func=lambda i:'티커 직접 입력' if i==-1 else f'{results[i]["ticker"]} · {results[i]["name"]}'+(' · 정보 미확인' if results[i].get('unverified') else ''),key=key+'choice')
    if choice!=-1:
        asset=results[choice]
        if asset['market']!=market:st.info('입력한 티커는 미국 종목입니다. 미국·달러 종목으로 등록합니다.' if asset['market']=='US' else '입력한 티커는 국내 종목입니다. 한국·원화 종목으로 등록합니다.')
        if asset.get('search_warning'):st.warning(asset['search_warning'])
        if asset.get('source')=='기본 종목 목록':st.caption('기본 종목 목록에서 선택했습니다. 현재 가격과 거래 가능 여부는 종가 조회로 확인하세요.')
        return asset
    ticker=st.text_input('티커',key=key+'ticker').strip().upper()
    name=st.text_input('종목명',key=key+'name')
    return {'ticker':ticker,'name':name,'market':market}

with st.sidebar:
    st.markdown('<div class="brand">◈ <b>Rebalance</b><small>PERSONAL ALLOCATION DESK</small></div>',unsafe_allow_html=True)
    today=datetime.now(ZoneInfo('Asia/Seoul')).date()
    day=st.date_input('종가 기준일',today,max_value=today)
    if st.button('종가 조회',type='primary',use_container_width=True):
        with st.spinner('종가·환율을 조회합니다…'):refresh(day)
    if st.session_state.demo:st.caption('DEMO · 설정에서 실제 전략과 자산을 입력하세요.')
    if st.session_state.dirty:st.caption('● 저장할 변경사항 있음')
    if connected and st.button('Sheets에 저장',disabled=st.session_state.demo,use_container_width=True):
        # Report on the main page: on phones the sidebar closes and a message here goes unseen.
        with st.spinner('Sheets에 저장하는 중…'):error=persist()
        if error:st.session_state.notice_error='Sheets 저장 실패: '+error
        else:st.session_state.notice=f'Sheets에 저장했습니다 ({datetime.now(ZoneInfo("Asia/Seoul")):%H:%M}). 저장 후 다시 읽어 내용이 같은지 확인했습니다.'
        st.rerun()
    st.download_button('전체 백업 다운로드',backup_bytes(ws()),'rebalance-backup.json','application/json',use_container_width=True)

# Menu sits at the top so it is visible on phones without opening the sidebar.
page=st.radio('메뉴',['이번달','월말 리밸런싱','월말 점검','리밸런싱','주문안','기록','설정'],horizontal=True,key='page',label_visibility='collapsed')
REDESIGNED=('이번달','월말 리밸런싱')  # pages already in design 2.0: no big title, own status lines
if page not in REDESIGNED:
    st.markdown('<div class="eyebrow">YOUR MONTHLY ALLOCATION</div>',unsafe_allow_html=True)
    st.title(page)
if page=='월말 리밸런싱':
    # The date lives in its own key so it survives steps where the date picker is not drawn.
    day=st.session_state.setdefault('rebal_date',today)
# Prices load by themselves (no button) once real holdings are in; the DEMO workspace waits for the button.
current=st.session_state.get('valued')
if page!='설정' and (page=='월말 리밸런싱' or not st.session_state.demo) and (not current or current['date']!=str(day)):
    with st.spinner('종가·환율을 불러옵니다…'):refresh(day)
descriptions={'월말 리밸런싱':'기준일 → 할 일 확인 → 체결 입력 → 마감, 순서대로 진행하세요.','이번달':'총자산과 계좌별 자산을 한눈에 확인하세요. 상세를 누르면 종목이 펼쳐집니다.','월말 점검':'GSM → DAA → ISA → 일반계좌 1 순서로(2026 전략이면 GSM → LAA → SSO → ISA) 규칙 판정을 확인하고, 반영할 전략만 직접 적용하세요.','리밸런싱':'종가와 월간 지표를 참고해 이번 달 목표 비중을 직접 정하세요.','주문안':'매수·매도 수량을 입력하고 자산 현황에 반영하세요.','기록':'현재 평가를 기록하고 Google Sheets로 내보내세요.','설정':'전략, 계좌, 종목과 보유수량을 직접 관리하세요.'}
if page not in REDESIGNED:st.caption(descriptions[page]+f' · 기준일 {day}')
if st.session_state.get('notice'):st.success(st.session_state.pop('notice'))
if st.session_state.get('notice_error'):st.error(st.session_state.pop('notice_error'))
if connected and st.session_state.get('dirty') and not st.session_state.demo and page not in REDESIGNED:st.caption('● Sheets에 저장하지 않은 변경이 있습니다 · 사이드바(») 「Sheets에 저장」')
result=st.session_state.get('valued');view=result['view'] if result and result['date']==str(day) else None
if page in ['이번달','월말 리밸런싱','월말 점검','리밸런싱','기록']:
    if view is None:st.info('예시(DEMO) 화면입니다. 사이드바(») 「종가 조회」로 가격을 불러오거나, 설정에서 실제 전략과 자산을 입력하세요.')
    else:
        for error in result['errors']:st.warning(error)

def go_rebalance():st.session_state.page='월말 리밸런싱'
def home_view(name):st.session_state.home_view=name

def monthly_chart(data,by,year):
    """100% stacked bar per month (1–12), validated stacking order, 2px white gaps, total (억) above each bar."""
    order=ui.STRATEGY_ORDER if by=='strategy' else ui.ASSET_ORDER
    keys=[k for k in order if k in set(data.key)]+[k for k in dict.fromkeys(data.key) if k not in order]
    months=[pd.Period(f'{year}-{i:02d}','M') for i in range(1,13)];labels=[f'{i}월' for i in range(1,13)]
    totals=data.groupby('month').value.sum().reindex(months)
    fig=go.Figure()
    for k in keys:
        d=data[data.key.eq(k)].groupby('month').value.sum().reindex(months)
        name=f'{data.loc[data.key.eq(k),"account"].iloc[-1]} {k}' if by=='strategy' and k in set(data.key) else k
        color=ui.strategy_color(k) if by=='strategy' else ui.asset_color(k)
        fig.add_bar(x=labels,y=d.values,name=name,marker=dict(color=color,line=dict(color='#fff',width=2)),customdata=(d/totals*100).values,
                    hovertemplate='%{x} · '+name+'<br>%{y:,.0f}원 · %{customdata:.1f}%<extra></extra>')
    fig.update_layout(barmode='stack',barnorm='percent',height=300,bargap=.28,margin=dict(t=26,b=8,l=4,r=4),paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',
                      font=dict(family='Pretendard, sans-serif',color='#191F28',size=12),showlegend=True,legend=dict(orientation='h',y=-.12,x=0,font=dict(size=11),traceorder='normal'),
                      yaxis=dict(visible=False,range=[0,100]),xaxis=dict(showgrid=False,tickfont=dict(color='#8B95A1')),hoverlabel=dict(font=dict(family='Pretendard')))
    for label,t in zip(labels,totals.values):
        if pd.notna(t):fig.add_annotation(x=label,y=100,yshift=12,text=f'{t/1e8:.2f}',showarrow=False,font=dict(size=10,color='#191F28'))
    return fig

if page=='이번달' and view is not None and st.session_state.get('home_view')=='monthly':
    st.button('← 홈',on_click=home_view,args=('',))
    by=st.radio('묶기',['계좌(전략)별','자산군별'],horizontal=True,key='monthly_by',label_visibility='collapsed')
    data=home.monthly(st.session_state.snapshots,'strategy' if by.startswith('계좌') else 'category')
    if data.empty:
        st.markdown(ui.card('<h2>월별 기록</h2><p class="ds-cap">아직 기록이 없어요. 월말 리밸런싱 마지막 단계에서 「이번 달 마감」을 누르면 그달 막대가 하나씩 쌓여요.</p>'),unsafe_allow_html=True)
    else:
        years=sorted({m.year for m in data.month},reverse=True);year=st.selectbox('연도',years,key='monthly_year') if len(years)>1 else years[0]
        data=data[data.month.map(lambda m:m.year)==year]
        with st.container(key='monthly_card'):
            st.markdown(f'<h2 class="ds-h2">월별 기록</h2><p class="ds-cap">{year}년 · 막대 위 숫자 = 총자산(억) · 막대를 누르면 아래에 금액이 나와요</p>',unsafe_allow_html=True)
            event=st.plotly_chart(monthly_chart(data,'strategy' if by.startswith('계좌') else 'category',year),use_container_width=True,config={'displayModeBar':False},on_select='rerun',selection_mode='points',key='monthly_plot')
        months=sorted(data.month.unique());picked=months[-1]
        points=(event or {}).get('selection',{}).get('points',[]) if isinstance(event,dict) else getattr(getattr(event,'selection',None),'points',[]) or []
        if points:
            label=points[0].get('x','');hit=[m for m in months if f'{m.month}월'==label]
            if hit:picked=hit[0]
        month=data[data.month.eq(picked)].sort_values('value',ascending=False);total=month.value.sum()
        before=data[data.month.eq(months[months.index(picked)-1])].value.sum() if months.index(picked)>0 else None
        rows=''.join(f'<li><span><i style="background:{ui.strategy_color(r.key) if by.startswith("계좌") else ui.asset_color(r.key)}"></i>{escape(str(r.account))} <small class="ds-label">{escape(str(r.key)) if by.startswith("계좌") else ""}</small></span><b>{ui.won(r.value,unit=False)} <small class="ds-label">{r.value/total*100:.1f}%</small></b></li>' for r in month.itertuples())
        st.markdown(ui.card(f'<div class="ds-link"><b class="ds-h2">{picked.year}년 {picked.month}월 말</b>{ui.change(total,before,pct=False)}</div>{ui.won_big(total)}<div class="ds-assets" style="grid-template-columns:1fr"><ul>{rows}</ul></div>'),unsafe_allow_html=True)

elif page=='이번달' and view is not None:
    checks={r['code']:r for r in checkup.check(st.session_state.holdings,st.session_state.strategies,view)}
    # Status line, then at most one alert line.
    saved=st.session_state.get('last_saved')
    status='● 저장 안 된 변경이 있어요 · 사이드바(») 「Sheets에 저장」' if connected and st.session_state.get('dirty') and not st.session_state.demo else \
           (f'✓ 시트 저장됨 · 오늘 {saved:%H:%M}' if saved else ('✓ 시트 연결됨' if connected else '시트 미연결 · 전체 백업으로 보관하세요'))
    st.markdown(f'<p class="ds-status">{status}</p>',unsafe_allow_html=True)
    flagged=[r for r in checks.values() if r['status']!='정상']
    if flagged:
        first=flagged[0];more=f' 외 {len(flagged)-1}개' if len(flagged)>1 else ''
        st.markdown(f'<div class="ds-alert {"bad" if first["status"]=="문제" else "warn"}">⚠ {escape(str(first["account"]))} — {escape(re.sub(r"\s*\(.*?\)","",re.split(r"\.(?:\s|$)",first["issues"][0][1])[0]))}{more} · 설정 › 계좌 점검에서 확인</div>',unsafe_allow_html=True)
    # Total card: 전일 / 지난 기록 대비 without 입출금, then principal and returns when 입출금 exists.
    complete=view.value.notna().all();total=view.value.sum() if complete else None
    prev=view.prev_value.sum() if 'prev_value' in view and view.prev_value.notna().all() else None
    record=m.last_record(st.session_state.snapshots,day)
    since=None if not record or total is None else record[1]+performance.net_flow(st.session_state.cashflows,record[0],day)
    rec_label=f'{pd.Timestamp(record[0]).month}월 말' if record else '지난 기록'
    perf=performance.summary(total,st.session_state.cashflows,day) if total is not None else None
    price_day=max(view.price_date.replace('',pd.NA).dropna(),default=str(day))
    stats=('<div class="ds-stats">'
           f'<div><span class="ds-label">투자 원금</span><b>{ui.won(perf["principal"],unit=False)}</b></div>'
           f'<div><span class="ds-label">총 수익률</span><b class="{"up" if (perf["return_pct"] or 0)>0 else "down"}">{"—" if perf["return_pct"] is None else f"{perf['return_pct']:+.1f}%"}</b></div>'
           f'<div><span class="ds-label">연환산</span><b class="{"up" if (perf["annual_pct"] or 0)>0 else "down"}">{"1년 뒤부터" if perf["annual_pct"] is None else f"{perf['annual_pct']:+.1f}%"}</b></div></div>') if perf else \
          '<p class="ds-cap" style="margin-top:12px">입출금을 기록하면 투자 원금 · 총 수익률 · 연환산 수익률이 나와요.</p>'
    st.markdown(ui.card(f'<span class="ds-label">총자산</span>{ui.won_big(total)}<div>{ui.change(total,prev,"전일")}&nbsp;&nbsp;{ui.change(total,since,rec_label)}</div>'
                        f'<p class="ds-cap">{"입금 제외 수익 기준 · " if record else ""}{pd.Timestamp(price_day):%m.%d} 종가 기준</p>{stats}'),unsafe_allow_html=True)
    # This month's to-do: judged accounts whose proposal differs from now.
    decisions=[d for d in rules.evaluate(view,day,prices,st.session_state.strategies) if d['status']!='판정 없음']
    todo=[d for d in decisions if d['changed']];blocked=[d for d in decisions if d['status']=='계산 불가']
    with st.container(key='todo_card'):
        n=len(todo);sub=' · '.join(f'{d["code"]} {home.todo_kind(d)}' for d in todo) or '판정한 계좌 모두 지금 비중 그대로'
        if blocked:sub+=f' · 계산 불가 {len(blocked)}'
        st.markdown(f'<div class="ds-todo"><span class="ds-todo-n {"none" if not n else ""}">{n}</span><span><b>{"이번 달 할 일 "+str(n)+"개" if n else "이번 달 할 일 없음"}</b><small>{escape(sub)}</small></span></div>',unsafe_allow_html=True)
        st.button('월말 리밸런싱 시작 ›',on_click=go_rebalance,key='todo_go',use_container_width=True)
    # Accounts, asset classes.
    judged={d['code']:True for d in decisions}
    day_change={c:(s.value.sum()/s.prev_value.sum()-1)*100 if 'prev_value' in s and s.prev_value.notna().all() and s.prev_value.sum() else None for c,s in view.groupby('strategy')}
    st.markdown(ui.card(f'<div class="ds-link"><h2>계좌</h2><span class="ds-label">{view.strategy.nunique()}개</span></div>{home.account_list(view,judged,checks,day_change)}<p class="ds-cap">줄을 누르면 목표·현재 도넛과 종목 막대가 펼쳐져요</p>'),unsafe_allow_html=True)
    if complete:st.markdown(ui.card(f'<div class="ds-link"><h2>자산군</h2><span class="ds-label">총자산 기준</span></div>{home.asset_card(view)}'),unsafe_allow_html=True)
    # Monthly record and broker check entry points.
    data=home.monthly(st.session_state.snapshots)
    with st.container(key='monthly_link'):
        months=sorted(data.month.unique()) if not data.empty else []
        first_last=f' · 첫 달 대비 {ui.change(data[data.month.eq(months[-1])].value.sum(),data[data.month.eq(months[0])].value.sum(),pct=False)}' if len(months)>1 else ''
        st.markdown(f'<div class="ds-link"><span><b>월별 기록</b><small>{len(months)}개월 기록{first_last if months else " · 「이번 달 마감」부터 쌓여요"}</small></span></div>',unsafe_allow_html=True)
        st.button('월별 기록 보기 ›',on_click=home_view,args=('monthly',),key='monthly_go',use_container_width=True)
    with st.expander('증권사 총액과 대조하기'):
        st.caption('증권사 앱의 계좌 총액을 넣으면 앱 평가액과 비교해요. 저장하지 않아요. 차이 0.5% 이하면 「일치」.')
        accounts=view.account.drop_duplicates().tolist();entered={}
        for i,account in enumerate(accounts):
            entered[account]=st.number_input(f'{account} 증권사 총액(원)',min_value=0.,step=10000.,format='%.0f',key=f'broker_total{i}')
        result_table=m.reconcile(view,entered)
        if not result_table.empty:
            rows=''.join(f'<li><span>{escape(str(r["계좌"]))}<small class="ds-label"> 앱 {ui.won(r["앱 평가액"],unit=False)} · 증권사 {ui.won(r["증권사 총액"],unit=False)}</small></span><b>{ui.tag("일치","same") if r["판정"]=="일치" else ui.tag(f"{r['차이(%)']:+.1f}%","warn")}</b></li>' for _,r in result_table.iterrows())
            st.markdown(f'<div class="ds-assets" style="grid-template-columns:1fr"><ul>{rows}</ul></div>',unsafe_allow_html=True)

elif page=='월말 리밸런싱' and view is not None:
    def goto(n):st.session_state.rstep=n
    def set_date(d):st.session_state.rebal_date=d
    def nav(back,label,target,key,disabled=False):
        """이전 / 다음 buttons side by side at the bottom of a step."""
        with st.container(key='nav_'+key):
            a,b=st.columns([1,2])
            if back:a.button('이전',on_click=goto,args=(back,),key='prev_'+key,use_container_width=True)
            return b.button(label,type='primary',key='next_'+key,use_container_width=True,disabled=disabled,on_click=None if target is None else goto,args=() if target is None else (target,))
    step=st.session_state.setdefault('rstep',1)
    confirmed=st.session_state.setdefault('rebal_confirmed',[]);filled=st.session_state.setdefault('rebal_filled',[])
    fractional=dict(zip(st.session_state.strategies.code,st.session_state.strategies.fractional_us)) if 'fractional_us' in st.session_state.strategies else {}
    decisions=[d for d in rules.evaluate(view,day,prices,st.session_state.strategies) if d['status']!='판정 없음']
    todo=[d for d in decisions if d['changed']];same=[d for d in decisions if d['status']=='판정' and not d['changed']];blocked=[d for d in decisions if d['status']=='계산 불가']
    name_of=dict(zip(view.strategy,view.account))
    st.markdown(ui.steps(step),unsafe_allow_html=True)
    if step==1:
        last=(pd.Timestamp(today)-pd.offsets.BDay(0)).date() if pd.Timestamp(today).dayofweek<5 else (pd.Timestamp(today)-pd.offsets.BDay(1)).date()
        month_end=(pd.Timestamp(today)+pd.offsets.BMonthEnd(0)).date()
        with st.container(key='step1_date'):
            st.markdown(f'<h2 class="ds-h1">{day.month}월 리밸런싱</h2><p class="ds-cap">이 날 종가를 월말 종가로 봅니다</p>',unsafe_allow_html=True)
            st.date_input('기준일',day,max_value=today,key='rebal_day_input',on_change=lambda:set_date(st.session_state.rebal_day_input))
            c1,c2,c3=st.columns(3)
            c1.button('마지막 거래일',on_click=set_date,args=(min(month_end,last),),key='chip_last',use_container_width=True)
            c2.button('오늘',on_click=set_date,args=(today,),key='chip_today',use_container_width=True)
            c3.caption('직접 선택은 위 날짜 칸')
        stocks=view[view.ticker.ne('CASH')];ok=stocks.value.notna()
        kr=stocks.fx.eq(1)|stocks.fx.isna()
        loaded=f'{view.price_date.replace("",pd.NA).dropna().max() or day}'
        rate=view.loc[view.fx.ne(1)&view.fx.notna(),'fx']
        rows=(f'<li><span>국내 ETF·주식</span><b>{int((ok&kr).sum())} / {int(kr.sum())}</b></li>'
              f'<li><span>미국 ETF·금시세</span><b>{int((ok&~kr).sum())} / {int((~kr).sum())}</b></li>'
              f'<li><span>환율</span><b>{"—" if rate.empty else f"{rate.iloc[0]:,.0f}원/$"}</b></li>')
        status=ui.tag('완료','same') if ok.all() else ui.tag(f'{int((~ok).sum())}개 못 불러옴','bad')
        st.markdown(ui.card(f'<div class="ds-link"><h2>가격 불러오기</h2>{status}</div><div class="ds-assets" style="grid-template-columns:1fr"><ul>{rows}</ul></div><p class="ds-cap">가격 날짜 {loaded}</p>'),unsafe_allow_html=True)
        for error in result['errors']:st.warning(error)
        chips=' '.join(ui.chip(d['code']) for d in decisions) or '없음'
        st.markdown(ui.card(f'<b>이번 달 판정하는 계좌</b><div style="margin:8px 0">{chips}</div><p class="ds-cap">나머지 계좌는 보유만(판정하지 않음)</p>'),unsafe_allow_html=True)
        nav(None,'판정 보기',2,'s1')
    elif step==2:
        n=len(todo)
        st.markdown(f'<h2 class="ds-h1">{"이번 달 할 일 "+str(n)+"개" if n else "이번 달 할 일 없음"}</h2><p class="ds-cap">{len(decisions)}개 계좌 판정 · {len(same)}개는 그대로</p>',unsafe_allow_html=True)
        picked={}
        for k,d in enumerate(todo,1):
            sub=view[view.strategy.eq(d['code'])];orders,notes=plan_orders(sub,d['targets'],bool(fractional.get(d['code'],False)))
            names=dict(zip(sub.ticker,sub.name));cats=dict(zip(sub.ticker,sub.category))
            moves=''.join(ui.bar_row(names.get(t,t),'',d['current'].get(t,0),w,ui.asset_color(cats.get(t,''))) for t,w in d['targets'].items() if t!='CASH' and abs(w-d['current'].get(t,0))>.5) if not orders else ''
            lines=''
            for o in orders:
                lines+=ui.order_line(o['side'],o['name'],o['shares'],o['amount'])
                if o.get('cut'):lines+=f'<p class="ds-cap" style="color:var(--up);margin:-4px 0 6px 52px">현금 부족으로 {o["cut"]:g}주 줄임</p>'
            cash=float(sub.loc[sub.ticker.eq('CASH'),'value'].sum())+sum(o['amount'] if o['side']=='매도' else -o['amount'] for o in orders);total=float(sub.value.sum())
            left=f'<div class="ds-link ds-cap" style="font-size:13px;margin-top:6px"><span>매매 후 남는 현금</span><b style="color:var(--text)">{ui.won(cash,unit=False)} ({cash/total*100 if total else 0:.1f}%)</b></div>' if orders else ''
            with st.container(key=f'judge_{d["code"]}'):
                st.markdown(f'<div class="ds-link"><span>{ui.chip(d["code"])} <b style="display:inline;font-size:17px">{escape(name_of.get(d["code"],d["code"]))}</b></span><span class="ds-label">{k}/{n}</span></div>'
                            f'<p style="font-size:16px;font-weight:700;margin:10px 0 2px">{escape(d["headline"])}</p>{moves}{lines}{left}',unsafe_allow_html=True)
                if d['evidence']:
                    with st.expander('근거 숫자'):table(pd.DataFrame(d['evidence']))
                picked[d['code']]=(st.checkbox('이 계좌 진행',value=True,key='go'+d['code']),d['targets'])
        for d in blocked:st.error(f'{d["code"]} {name_of.get(d["code"],"")}: 계산 불가 · {d["headline"]}')
        if same:
            rows=''.join(f'<li><span>{ui.chip(d["code"])} 그대로</span><small class="ds-label">{escape(d["headline"].split("→")[0].strip()[:24])}</small></li>' for d in same)
            st.markdown(ui.card(f'<div class="ds-assets" style="grid-template-columns:1fr"><ul>{rows}</ul></div>'),unsafe_allow_html=True)
        go=[c for c,(g,_) in picked.items() if g]
        if nav(1,f'체결하러 가기 ({len(go)}개 계좌)' if picked else '바로 마감',None,'s2'):
            try:
                h=st.session_state.holdings
                for code,(g,targets) in picked.items():
                    if g:h=rules.apply_targets(h,code,targets)
                if go:install({'holdings':m.validate_holdings(h)});refresh(day)
                st.session_state.rebal_confirmed=go;st.session_state.rebal_filled=[];st.session_state.rstep=3 if go else 4
                error=persist() if go else None
                if go:st.session_state['notice_error' if error else 'notice']='목표 비중을 확정했어요. 증권사 앱에서 주문한 뒤 체결을 입력하세요.'+saved_note(error)
                st.rerun()
            except DataError as e:st.error(str(e))
    elif step==3:
        remaining={};total_orders=len(filled)
        for code in confirmed:
            sub=view[view.strategy.eq(code)]
            if not sub.empty:remaining[code]=plan_orders(sub,dict(zip(sub.ticker,sub.target_pct)),bool(fractional.get(code,False)))[0];total_orders+=len(remaining[code])
        st.markdown(f'<h2 class="ds-h1">주문 {total_orders}건 중 {len(filled)}건 반영</h2><p class="ds-cap">증권사 앱에서 체결 후 숫자를 맞춰 주세요</p>',unsafe_allow_html=True)
        if not confirmed:st.info('2 할 일에서 진행할 계좌를 고르세요. 앱을 다시 열었다면 2단계에서 한 번 더 누르면 남은 주문만 나와요.')
        for code in confirmed:
            with st.container(key=f'fillcard_{code}'):
                st.markdown(f'<div>{ui.chip(code)} <b style="font-size:17px">{escape(name_of.get(code,code))}</b></div><p class="ds-cap">매도 먼저 → 그 돈으로 매수</p>',unsafe_allow_html=True)
                for f in [f for f in filled if f['code']==code]:
                    st.markdown(f'<div class="ds-order done"><span class="ds-order-icon">{"↓" if f["side"]=="매도" else "↑"}</span><b>{escape(f["name"])}<small class="ds-cap" style="display:block">{f["shares"]:g}주 × {f["price"]:,.2f} = {f["amount"]:,.0f}원</small></b>{ui.tag("반영됨","same")}</div>',unsafe_allow_html=True)
                orders=remaining.get(code,[])
                if not orders:st.markdown('<p class="ds-cap">남은 주문 없음</p>',unsafe_allow_html=True)
                for i,o in enumerate(orders):
                    key=f'{code}{i}{st.session_state.revision}';usd=o['fx']!=1  # priced in dollars (valuation decides the market from the ticker)
                    side='buy' if o['side']=='매수' else 'sell'
                    with st.container(key=f'ticket_{side}_{key}'):
                        st.markdown(f'<div class="ticket-head"><span class="ticket-side {side}">{o["side"]}</span><b>{escape(o["name"])}</b><small class="ds-label" style="margin-left:auto">{escape(o["ticker"])}</small></div>',unsafe_allow_html=True)
                        px_in=st.number_input(f'체결가 ({"달러" if usd else "원"})',min_value=0.,value=float(o['close']),step=.01 if usd else 5.,format='%.2f' if usd else '%.0f',key='px'+key)
                        q=st.number_input('수량 (주)',min_value=0.,value=float(o['shares']),step=1.,format='%g',key='qty'+key)
                        amount=q*px_in*o['fx']
                        st.markdown(f'<div class="ticket-amount"><span>주문금액</span><b class="{side}">{amount:,.0f}원<small class="ds-cap" style="display:block;text-align:right">약 {ui.won(o["amount"],unit=False)} · 제안 그대로{"" if q==o["shares"] else " 아님"}</small></b></div>',unsafe_allow_html=True)
                        if st.button('체결 반영',key='fill'+key,type='primary',use_container_width=True):
                            try:
                                updated,before,after=apply_fill(st.session_state.holdings,code,o['ticker'],o['side'],q,px_in*o['fx'])
                                log=m.action(updated,code,o['ticker'],q,o['side'],day,before,after,px_in,o['fx'])
                                install({'holdings':updated,'actions':pd.concat([st.session_state.actions,pd.DataFrame([log])],ignore_index=True)})
                                st.session_state.valued={'date':str(day),'view':m.revalue(view,updated),'errors':result['errors']}
                                st.session_state.rebal_filled=filled+[dict(code=code,name=o['name'],side=o['side'],shares=q,price=px_in,amount=amount)]
                                error=persist()
                                st.session_state['notice_error' if error else 'notice']=f'{o["name"]} {o["side"]} {q:g}주 반영 · {before:g} → {after:g}.'+saved_note(error)
                                st.rerun()
                            except DataError as e:st.error(str(e))
        skipped=[d['code'] for d in todo if d['code'] not in confirmed]
        if skipped:st.markdown(ui.card(''.join(f'<div class="ds-link"><span>{ui.chip(c)} {escape(name_of.get(c,c))}</span><small class="ds-label">진행 안 함 · 건너뜀</small></div>' for c in skipped)),unsafe_allow_html=True)
        nav(2,'마감하러 가기',4,'s3')
    else:
        total=view.value.sum() if view.value.notna().all() else None
        record=m.last_record(st.session_state.snapshots,day);flow=performance.net_flow(st.session_state.cashflows,record[0],day) if record else 0
        prev_label=f'{pd.Timestamp(record[0]).month}월 말 대비' if record else '지난 기록 대비'
        extra=f'<p class="ds-cap">입금 {ui.won(flow,unit=False)} 제외 수익 {ui.change(total,record[1]+flow,pct=False)}</p>' if record and flow else ''
        st.markdown(ui.card(f'<span class="ds-label">{day.month}월 말 총자산</span>{ui.won_big(total)}<div>{ui.change(total,record[1] if record else None,prev_label)}</div>{extra}'),unsafe_allow_html=True)
        with st.container(key='close_check'):
            st.markdown('<div class="ds-link"><h2 class="ds-h2">증권사 총액 대조</h2></div><p class="ds-cap">증권사 앱의 계좌 총액을 넣으면 0.5% 이하 차이는 「일치」. 금·현금·소액 계좌는 생략해도 돼요.</p>',unsafe_allow_html=True)
            entered={}
            for i,(account,sub) in enumerate(view.groupby('account',sort=False)):
                entered[account]=st.number_input(f'{account} · 앱 {ui.won(sub.value.sum(),unit=False)}',min_value=0.,step=10000.,format='%.0f',key=f'close_total{i}')
            checked=m.reconcile(view,entered)
            if not checked.empty:
                rows=''.join(f'<li><span>{escape(str(r["계좌"]))}<small class="ds-label"> 앱 {ui.won(r["앱 평가액"],unit=False)} · 증권사 {ui.won(r["증권사 총액"],unit=False)}</small></span><b>{ui.tag("일치","same") if r["판정"]=="일치" else ui.tag(f"{r['차이(%)']:+.1f}%","warn")}</b></li>' for _,r in checked.iterrows())
                st.markdown(f'<div class="ds-assets" style="grid-template-columns:1fr"><ul>{rows}</ul></div>',unsafe_allow_html=True)
        n_fill=len(filled)
        st.markdown(ui.card(f'<b>마감하면 한 번에</b><p class="ds-cap">· {day.month}월 기록 1줄 저장 (계좌·자산군별 금액)<br>· 체결 {n_fill}건 수량 반영 · 시트 저장</p>'),unsafe_allow_html=True)
        memo=st.text_input('메모 (선택)',key='close_memo')
        if nav(3,'이번 달 마감',None,'s4'):
            try:
                install({'snapshots':snapshot_table(view,day,memo)});refresh(day)
                error=persist();st.session_state.rebal_confirmed=[];st.session_state.rebal_filled=[];st.session_state.rstep=1
                st.session_state['notice_error' if error else 'notice']=f'{day.month}월을 마감했어요. 기록을 남겼어요.'+saved_note(error)
                st.rerun()
            except DataError as e:st.error(str(e))

elif page=='월말 점검' and view is not None:
    st.caption('앱은 제안만 합니다. 「목표 비중에 반영」을 누른 전략만 목표 비중이 바뀌고, 매매는 주문안에서 직접 입력합니다.')
    names=dict(zip(view.ticker,view.name))
    for d in rules.evaluate(view,day,prices,st.session_state.strategies):
        tone={'판정':'judged','판정 없음':'skipped','계산 불가':'blocked'}[d['status']]
        badge='변경 제안' if d['changed'] else ('유지' if d['status']=='판정' else d['status'])
        with st.container(border=True):
            st.markdown(f'<div class="check-card {tone}"><div class="card-top"><h3>{escape(d["code"])}</h3><span class="check-badge">{escape(badge)}</span></div><p class="check-headline">{escape(d["headline"])}</p></div>',unsafe_allow_html=True)
            if d['evidence']:table(pd.DataFrame(d['evidence']))
            if d['changed']:
                plan=pd.DataFrame([dict(종목=names.get(t,t),현재=d['current'].get(t,0.),제안=w) for t,w in d['targets'].items()])
                st.dataframe(plan,hide_index=True,use_container_width=True,column_config={c:st.column_config.NumberColumn(format='%.2f%%') for c in ['현재','제안']})
                if st.button('목표 비중에 반영',key='apply_rule'+d['code']):
                    try:
                        install({'holdings':m.validate_holdings(rules.apply_targets(st.session_state.holdings,d['code'],d['targets']))});refresh(day)
                        st.session_state.notice=f'{d["code"]} 목표 비중을 제안대로 바꿨습니다. 주문안에서 매매 수량을 입력하세요.';st.rerun()
                    except DataError as e:st.error(str(e))

elif page=='리밸런싱' and view is not None:
    st.caption('현재 비중: 🔴 목표 초과 · 🟢 목표와 같음 · 🔵 목표 미달 (소수점 둘째 자리 기준)')
    st.caption('SMA와 수익률: 비수정 월말 종가 기준이며, 기준일 종가를 그달의 월말 종가로 씁니다. 평가액은 원화 환산, 종가·SMA는 종목의 거래 통화입니다.')
    for code,sub in view.groupby('strategy',sort=False):
        st.subheader(code)
        shown=sub[['strategy','ticker','name','shares','market','close','sma10','value','weight','target_pct','return12']].copy()
        shown.market=shown.market.map({'KR':'원화','US':'달러'})
        shown.columns=['전략명','티커','종목명','보유 수량','원화/달러','종가','10개월 SMA','평가액','현재 비중','목표 비중','12개월 수익률']
        st.markdown(portfolio_table(sub),unsafe_allow_html=True)
        st.caption('목표 비중 편집 · 현재 비중과 비교하며 입력하세요.')
        target_editor=shown[['티커','종목명','현재 비중','목표 비중']].copy()
        with st.form('plan'+code+str(st.session_state.revision)):
            edited=st.data_editor(target_editor,hide_index=True,use_container_width=True,disabled=['티커','종목명','현재 비중'],column_config={**price_columns(target_editor.columns),'목표 비중':st.column_config.NumberColumn(min_value=0.,max_value=100.,format='%.2f%%'),'현재 비중':st.column_config.NumberColumn(format='%.2f%%'),'12개월 수익률':st.column_config.NumberColumn(format='%.2f%%')})
            if st.form_submit_button('목표 비중 적용'):
                try:
                    values=[m.number(x,'목표비중',100) for x in edited['목표 비중']]
                    if abs(sum(values)-100)>.01:raise DataError('목표 비중 합계가 100%여야 합니다')
                    h=st.session_state.holdings.copy();mask=h.strategy.eq(code);targets=dict(zip(edited['티커'],values));h.loc[mask,'target_pct']=h.loc[mask,'ticker'].map(targets)
                    install({'holdings':m.validate_holdings(h)});refresh(day);st.session_state.notice='목표 비중을 적용했습니다.';st.rerun()
                except DataError as e:st.error(str(e))

elif page=='주문안':
    st.info('매수는 입력 수량을 더하고, 매도는 뺍니다. 실제 증권 주문을 전송하지 않으며 현금은 자동 정산하지 않습니다.')
    codes=st.session_state.holdings.strategy.drop_duplicates().tolist()
    if not codes:st.info('설정에서 전략을 먼저 추가하세요.')
    for code in codes:
        st.subheader(code);h=st.session_state.holdings;sub=h[h.strategy.eq(code)&h.ticker.ne('CASH')]
        source=st.radio('종목 선택',['보유·후보 종목','새 종목'],horizontal=True,key='order_source'+code)
        if source=='새 종목':
            asset=picker('order'+code)
            if st.button('후보로 등록',key='order_add'+code):
                try:apply({'holdings':m.add_asset(h,code,asset)},'수량 0인 후보로 등록했습니다. 보유·후보 종목에서 선택하세요.')
                except DataError as e:st.error(str(e))
        elif sub.empty:st.caption('등록된 종목이 없습니다. 새 종목을 검색해 추가하세요.')
        else:
            ticker=st.selectbox('종목',sub.ticker.tolist(),format_func=lambda t:f'{t} · {sub.loc[sub.ticker.eq(t),"name"].iloc[0]}',key='order_ticker'+code)
            current=float(sub.loc[sub.ticker.eq(ticker),'shares'].iloc[0])
            quote=view.loc[view.strategy.eq(code)&view.ticker.eq(ticker)] if view is not None else pd.DataFrame()
            value='—';weight='—'
            if not quote.empty:
                r=quote.iloc[0]
                value='—' if pd.isna(r.value) else f'{r.value:,.0f}원'
                weight='—' if pd.isna(r.weight) else weight_html(r.weight,r.target_pct)
            quantity=f'{current:,.4f}'.rstrip('0').rstrip('.')
            st.markdown(f'<div class="order-summary"><div><small>현재 보유수량</small><b>{quantity}주</b></div><div><small>현재 평가액</small><b>{value}</b></div><div><small>현재 비중 · 전략 내</small><b>{weight}</b></div></div>',unsafe_allow_html=True)
            if quote.empty:st.caption('종가를 조회하면 평가액과 비중을 표시합니다.')
            with st.form('order_form'+code):
                q=st.number_input('매매할 수량',min_value=0.,step=1.,format='%.4f')
                a,b=st.columns(2);buy=a.form_submit_button('매수',use_container_width=True);sell=b.form_submit_button('매도',use_container_width=True)
                if buy or sell:
                    try:
                        if quote.empty or pd.isna(quote.iloc[0].close) or pd.isna(quote.iloc[0].fx):
                            raise DataError('매매를 반영하기 전에 선택한 기준일의 종가를 조회하세요')
                        side='매수' if buy else '매도';updated,before,after=m.adjust(h,code,ticker,q,side)
                        changed_view=m.revalue(view,updated)
                        log=m.action(updated,code,ticker,q,side,day,before,after)
                        install({'holdings':updated,'actions':pd.concat([st.session_state.actions,pd.DataFrame([log])],ignore_index=True)})
                        st.session_state.valued={'date':str(day),'view':changed_view,'errors':result['errors']}
                        st.session_state.notice=f'{ticker} {side} {q:g}주 반영 · {before:g} → {after:g} · 조회된 종가로 평가액과 비중을 재계산했습니다.'
                        st.rerun()
                    except DataError as e:st.error(str(e))

elif page=='기록':
    memo=st.text_input('평가 메모')
    if st.button('평가 기록 확정',disabled=view is None):
        try:
            apply({'snapshots':snapshot_table(view,day,memo)},'평가를 기록했습니다.')
        except DataError as e:st.error(str(e))
    selected=st.selectbox('내보낼 시트',TABLES);table(st.session_state[selected]);st.code(to_tsv(st.session_state[selected]),language=None)
    st.download_button('CSV 다운로드',to_csv_bytes(st.session_state[selected]),selected+'.csv','text/csv')

elif page=='설정':
    tabs=st.tabs(['계좌 점검','전략 관리','종목·수량·비중','2027 전략 템플릿','원장·백업'])
    with tabs[0]:
        st.caption('계좌마다 어떤 규칙이 걸리는지, 주문이나 판정을 틀리게 만들 칸이 있는지 보여 줍니다. 「고치기」에서 역할과 목표 비중을 바로 고칠 수 있습니다.')
        results=checkup.check(st.session_state.holdings,st.session_state.strategies,view)
        if view is None:st.caption('가격을 불러오면 「가격 없음」과 「목표와 실제 차이」도 점검합니다.')
        free=[c for c in rules.ORDER if c not in set(st.session_state.holdings.strategy)]
        for r in results:
            badge={'문제':'blocked','확인':'judged','정상':'skipped'}[r['status']]
            with st.container(border=True):
                st.markdown(f'<div class="check-card {badge}"><div class="card-top"><h3>{escape(str(r["account"]))}</h3><span class="check-badge">{escape(r["code"])} · {r["status"]}</span></div><p class="check-rule">{"⚙️ " if r["judged"] else ""}{escape(r["rule"])}</p></div>',unsafe_allow_html=True)
                for level,text in r['issues']:(st.error if level=='문제' else st.warning)(text)
                with st.expander('고치기'):
                    h=st.session_state.holdings;sub=h[h.strategy.eq(r['code'])]
                    shown=sub[['name','ticker','role','target_pct']].rename(columns={'name':'종목','ticker':'티커','role':'역할','target_pct':'목표 (%)'})
                    with st.form('fix'+r['code']+str(st.session_state.revision)):
                        edited=st.data_editor(shown,hide_index=True,use_container_width=True,disabled=['종목','티커'],column_config={'역할':st.column_config.SelectboxColumn(options=list(dict.fromkeys(checkup.ROLES+sub.role.tolist()))),'목표 (%)':st.column_config.NumberColumn(min_value=0.,max_value=100.,format='%g')})
                        st.caption(f'목표 합계 {sub.target_pct.sum():g}% → 100%가 되게 맞추세요. 역할은 판정에 쓰는 값(현금·필터·레버리지)만 남기고 나머지는 비우세요.')
                        if st.form_submit_button('저장',use_container_width=True):
                            try:
                                updated=h.copy();updated.loc[sub.index,['role','target_pct']]=edited[['역할','목표 (%)']].to_numpy()
                                st.session_state.demo=False;install({'holdings':m.validate_holdings(updated)});error=persist()
                                st.session_state.notice=f'{r["code"]} 계좌를 고쳤습니다.'+(f' (Sheets 저장 실패: {error})' if error else '');st.rerun()
                            except DataError as e:st.error(str(e))
                    if not r['judged']:
                        st.caption('전략 코드 바꾸기 · 계좌 이름은 그대로 두고 코드만 바꿉니다. 규칙은 코드로 정해집니다(예: EM = 2027 일반계좌 규칙).')
                        labels=[f'{c} · {checkup.describe(c,checkup.params_of(st.session_state.strategies,c))}' for c in free]
                        new=st.selectbox('바꿀 코드',['그대로']+labels+['직접 입력(규칙 없음)'],key='rule_for'+r['code']).split(' · ')[0]
                        if new=='직접 입력(규칙 없음)':new=st.text_input('새 코드(영문, 예: SAMSUNG)',key='rule_text'+r['code']).strip().upper() or '그대로'
                        if new!='그대로' and st.button(f'{r["code"]} → {new}로 바꾸기',key='rename'+r['code']):
                            conf=st.session_state.strategies;desc=conf.loc[conf.code.eq(r['code']),'description']
                            try:apply(m.change_strategy(ws(),r['code'],new,str(r['account']),str(desc.iloc[0]) if not desc.empty else ''),f'{r["code"]}를 {new}로 바꿨습니다. 계좌 이름과 과거 기록은 그대로입니다.')
                            except DataError as e:st.error(str(e))
    with tabs[1]:
        with st.expander('새 전략 추가',expanded=st.session_state.holdings.empty):
            with st.form('new_strategy'):
                name=st.text_input('전략명');account=st.text_input('계좌명');description=st.text_input('설명')
                if st.form_submit_button('전략 추가'):
                    try:
                        data=m.add_strategy(ws(),name,account,description);st.session_state.demo=False;apply(data,'전략을 추가했습니다.')
                    except DataError as e:st.error(str(e))
        codes=sorted(set(st.session_state.strategies.code)|set(st.session_state.holdings.strategy))
        if codes:
            code=st.selectbox('관리할 전략',codes,key='manage_strategy')
            h=st.session_state.holdings;conf=st.session_state.strategies;row=conf[conf.code.eq(code)]
            account=row.account.iloc[0] if not row.empty else h.loc[h.strategy.eq(code),'account'].iloc[0]
            description=row.description.iloc[0] if not row.empty else ''
            with st.form('change'+code+str(st.session_state.revision)):
                name=st.text_input('전략명 변경',code);account_new=st.text_input('계좌명 변경',account);desc=st.text_input('설명 변경',description)
                if st.form_submit_button('변경 적용'):
                    try:apply(m.change_strategy(ws(),code,name,account_new,desc),'전략 정보를 변경했습니다. 과거 기록은 보존됩니다.')
                    except DataError as e:st.error(str(e))
            confirm=st.checkbox('이 전략을 현재 목록에서 삭제합니다. 과거 기록은 보존됩니다.',key='delete_confirm'+code)
            if st.button('전략 삭제',disabled=not confirm,key='delete_strategy'+code):
                try:apply(m.delete_strategy(ws(),code),'전략을 삭제했습니다.')
                except DataError as e:st.error(str(e))
    with tabs[2]:
        h=st.session_state.holdings;codes=h.strategy.drop_duplicates().tolist()
        if not codes:st.info('전략 관리에서 전략을 먼저 추가하세요.')
        else:
            code=st.selectbox('전략',codes,key='asset_strategy');sub=h[h.strategy.eq(code)].copy()
            st.caption('보유수량은 최종 잔고입니다. CASH 수량은 원화 현금 잔액입니다. 후보 종목은 수량 0으로 등록하세요. 역할: LAA 필터 종목은 「필터」, SSO·ISA 매수 종목은 「레버리지」(비워 두면 종목명으로 찾습니다). DAA·ISA·일반계좌 1의 현금 몫은 템플릿의 단기채권(153130) 행에 둡니다.')
            labels={'ticker':'티커','name':'종목명','market':'시장','category':'자산 분류','role':'역할','shares':'보유수량','target_pct':'목표비중 (%)'}
            shown=sub[list(labels)].rename(columns=labels)
            with st.form('edit_assets'+code+str(st.session_state.revision)):
                edited=st.data_editor(shown,hide_index=True,use_container_width=True,disabled=['티커','시장'],column_config={'자산 분류':st.column_config.SelectboxColumn(options=list(dict.fromkeys(m.CATEGORIES+sub.category.tolist()))),'보유수량':st.column_config.NumberColumn(min_value=0.,format='%.4f'),'목표비중 (%)':st.column_config.NumberColumn(min_value=0.,max_value=100.,format='%.2f')})
                st.caption(f'현재 저장된 목표비중 합계 {sub.target_pct.sum():.2f}% · 합계 100%가 아니어도 작성 중인 계획을 저장할 수 있습니다.')
                if st.form_submit_button('보유수량·목표비중 적용'):
                    try:
                        updated=h.copy();updated.loc[sub.index,['name','category','role','shares','target_pct']]=edited[['종목명','자산 분류','역할','보유수량','목표비중 (%)']].to_numpy()
                        st.session_state.demo=False;apply({'holdings':m.validate_holdings(updated)},'수량과 목표비중을 적용했습니다.')
                    except DataError as e:st.error(str(e))
            if abs(sub.target_pct.sum()-100)>.01:st.warning('목표비중 합계가 100%가 아닙니다. 리밸런싱 전에 조정하세요.')
            if m.GOLD_TICKER not in set(sub.ticker) and st.button('금 현물(g) 항목 추가',key='add_gold'+code,help='국제 금시세(달러/온스) × 원/달러 ÷ 31.1035로 1g 가격을 추정합니다. 추가한 뒤 보유수량에 g 수를 입력하세요.'):
                try:apply({'holdings':m.add_asset(h,code,m.GOLD_ASSET)},'금 현물 항목을 추가했습니다. 보유수량에 g 수를 입력하세요.')
                except DataError as e:st.error(str(e))
            with st.expander('종목 검색·추가',expanded=False):
                asset=picker('settings'+code)
                with st.form('asset_add'+code):
                    shares=st.number_input('추가할 보유수량',min_value=0.,step=1.,format='%.4f');target=st.number_input('추가할 목표비중 (%)',min_value=0.,max_value=100.,step=1.)
                    if st.form_submit_button('전략에 종목 추가'):
                        try:apply({'holdings':m.add_asset(h,code,asset,shares,target)},'종목을 추가했습니다.')
                        except DataError as e:st.error(str(e))
            options=sub.loc[sub.ticker.ne('CASH'),'ticker'].tolist()
            if options:
                ticker=st.selectbox('삭제할 종목',options,key='delete_asset_select'+code)
                if st.button('종목 삭제',key='delete_asset'+code):
                    try:apply({'holdings':m.delete_asset(h,code,ticker)},'종목을 삭제했습니다.')
                    except DataError as e:st.error(str(e))
    with tabs[3]:
        try:template=load_template()
        except (OSError,ValueError,DataError) as e:template=None;st.error(f'템플릿을 읽지 못했습니다: {e}')
        if template:
            st.caption(f'{template["name"]} · 시작일 {template["effective_date"]} · 계좌별 전략 매핑입니다. 보유 수량은 바꾸지 않고, 전략 규칙·종목 목록·고정 목표 비중만 맞춥니다.')
            table(mapping_table(template))
            if st.button('적용하면 바뀌는 내용 미리 보기'):
                try:st.session_state.template_preview=apply_template(st.session_state.holdings,st.session_state.strategies,st.session_state.strategy_versions,template)
                except DataError as e:st.error(str(e))
            preview=st.session_state.get('template_preview')
            if preview:
                table(preview[3])
                st.caption('금 현물(GC=F) 수량은 g ÷ 31.1035(트로이온스)로 입력하세요. 새 종목은 수량 0으로 들어가니 실제 수량을 「종목·수량·비중」에서 입력하세요.')
                ok=st.checkbox('위 내용을 확인했습니다. 이전 전략 설정은 전략 이력에 보관됩니다.',key='template_confirm')
                if st.button('2027 템플릿 적용',disabled=not ok,type='primary'):
                    h,conf,versions,_=st.session_state.pop('template_preview')
                    st.session_state.demo=False
                    apply({'holdings':h,'strategies':conf,'strategy_versions':versions},'2027 전략 템플릿을 적용했습니다.')
    with tabs[4]:
        st.caption('기존 Apps Script 연결과 Sheets 저장·충돌 확인 방식은 유지됩니다.')
        if connected and st.button('최신 원장 미리보기'):
            try:st.session_state.preview=load_workspace(remote['SHEETS_WEBAPP_URL'],remote['SHEETS_SECRET'])
            except DataError as e:st.error(str(e))
        if st.session_state.get('preview'):
            data,token=st.session_state.preview;table(data['holdings'])
            if st.button('미리 본 원장 적용'):
                st.session_state.token=token;st.session_state.demo=False;data=st.session_state.pop('preview')[0];apply(data,'원장을 적용했습니다.',save=False)
        file=st.file_uploader('보유내역 CSV·TSV',type=['csv','tsv'])
        if file and st.button('보유내역 가져오기'):
            try:st.session_state.demo=False;apply({'holdings':m.validate_holdings(parse_table(file.getvalue()))},'보유내역을 가져왔습니다.',save=False)
            except DataError as e:st.error(str(e))
        backup=st.file_uploader('전체 백업 JSON',type=['json'])
        if backup and st.button('백업 복원'):
            try:st.session_state.demo=False;apply(restore_backup(backup.getvalue()),'백업을 복원했습니다.',save=False)
            except DataError as e:st.error(str(e))

st.caption(f'앱 버전 {APP_VERSION}')
