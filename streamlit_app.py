from datetime import datetime
from zoneinfo import ZoneInfo
from html import escape
from pathlib import Path
import hashlib
import hmac
import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_app import manual as m
from streamlit_app.tables import portfolio_table, weight_html
from streamlit_app.data import DataError, load_default_holdings, load_default_strategies, normalize_strategies, to_csv_bytes, to_tsv
from streamlit_app.ledger import TABLES, empty_workspace, backup_bytes, restore_backup, parse_table
from streamlit_app.sheets_sync import load_workspace, save_workspace

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

def apply(data,message):
    install(data);st.session_state.notice=message;st.rerun()

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
def prices(t,market,day):return m.fetch_prices(t,market,day)
def find(query,market,mode):return m.search(query,market,mode)

def refresh(day):
    v,errors=m.valuation(st.session_state.holdings,day,prices)
    st.session_state.valued={'date':str(day),'view':v,'errors':errors}

def price_columns(columns):
    return {c:st.column_config.NumberColumn(format='localized') for c in columns
            if c in ['종가','10개월 SMA','close','sma10','actual_price','평가액','value','actual_amount','planned_amount']}

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
    page=st.radio('메뉴',['이번달','리밸런싱','주문안','기록','설정'],label_visibility='collapsed')
    today=datetime.now(ZoneInfo('Asia/Seoul')).date()
    day=st.date_input('종가 기준일',today,max_value=today)
    if st.button('종가 조회',type='primary',use_container_width=True):
        with st.spinner('종가·환율을 조회합니다…'):refresh(day)
    if st.session_state.demo:st.caption('DEMO · 설정에서 실제 전략과 자산을 입력하세요.')
    if st.session_state.dirty:st.caption('● 저장할 변경사항 있음')
    if connected and st.button('Sheets에 저장',disabled=st.session_state.demo,use_container_width=True):
        try:
            st.session_state.token=save_workspace(remote['SHEETS_WEBAPP_URL'],remote['SHEETS_SECRET'],ws(),st.session_state.token)
            st.session_state.dirty=False;st.success('저장·재조회 확인 완료')
        except DataError as e:st.error(str(e))
    st.download_button('전체 백업 다운로드',backup_bytes(ws()),'rebalance-backup.json','application/json',use_container_width=True)

st.markdown('<div class="eyebrow">YOUR MONTHLY ALLOCATION</div>',unsafe_allow_html=True)
st.title(page)
descriptions={'이번달':'전략별 자산 규모와 현재 비중을 한눈에 확인하세요.','리밸런싱':'종가와 월간 지표를 참고해 이번 달 목표 비중을 직접 정하세요.','주문안':'매수·매도 수량을 입력하고 자산 현황에 반영하세요.','기록':'현재 평가를 기록하고 Google Sheets로 내보내세요.','설정':'전략, 계좌, 종목과 보유수량을 직접 관리하세요.'}
st.caption(descriptions[page]+f' · 기준일 {day}')
if st.session_state.get('notice'):st.success(st.session_state.pop('notice'))
result=st.session_state.get('valued');view=result['view'] if result and result['date']==str(day) else None
if page in ['이번달','리밸런싱','기록']:
    if view is None:st.info('사이드바의 종가 조회를 눌러 선택한 기준일의 평가를 불러오세요.')
    else:
        for error in result['errors']:st.warning(error)

if page=='이번달' and view is not None:
    complete=view.value.notna().all();total=f'{view.value.sum():,.0f}원' if complete else '조회 확인 필요'
    st.markdown(f'<div class="hero"><span>총 평가액 · 원화 환산</span><strong>{total}</strong><small>{view.strategy.nunique()}개 전략 · {day} 기준</small></div>',unsafe_allow_html=True)
    st.subheader('자산군 분포')
    if complete:
        categories=m.category_distribution(view)
        if categories.empty:st.caption('평가액이 있는 자산이 없습니다.')
        else:
            chart=px.pie(categories,names='category',values='value',hole=.74,
                color_discrete_sequence=['#3567E8','#32999D','#9B76CE','#B7C6DA','#F4B860','#E78E9A','#8CABC2'])
            chart.update_traces(textinfo='percent',textposition='inside',
                hovertemplate='%{label}<br>%{value:,.0f}원 · %{percent}<extra></extra>')
            chart.update_layout(height=340,margin=dict(t=15,b=15,l=30,r=30),showlegend=True,
                paper_bgcolor='rgba(0,0,0,0)',font=dict(family='Pretendard, sans-serif',color='#1C2E49',size=14),legend=dict(orientation='h',y=-.05,x=.5,xanchor='center'))
            with st.container(border=True):
                st.plotly_chart(chart,use_container_width=True,config={'displayModeBar':False})
    else:st.caption('모든 종가와 환율 조회를 완료하면 분포를 표시합니다.')
    st.subheader('전략별 자산')
    st.caption('현재 비중: 🔴 목표 초과 · 🟢 목표와 같음 · 🔵 목표 미달 (소수점 둘째 자리 기준)')
    cards=[]
    for code,sub in view.groupby('strategy',sort=False):
        amount=f'{sub.value.sum():,.0f}원' if sub.value.notna().all() else '조회 확인 필요';lines=[]
        for r in sub.to_dict('records'):
            value='—' if pd.isna(r['value']) else f'{r["value"]:,.0f}원';weight='—' if pd.isna(r['weight']) else weight_html(r['weight'],r['target_pct'])
            lines.append(f'<div class="asset-line"><span>{escape(r["name"])}<small>{escape(r["ticker"])} · {escape(r["price_date"])}</small></span><span>{value}</span><b>{weight}</b></div>')
        cards.append(f'<article class="strategy-card"><div class="card-top"><h3>{escape(code)}</h3><span>{len(sub)}종목</span></div><small>{escape(str(sub.account.iloc[0]))}</small><div class="card-amount">{amount}</div><div class="asset-head"><span>종목</span><span>평가액</span><span>비중</span></div>{"".join(lines)}</article>')
    st.markdown('<div class="strategy-grid">'+''.join(cards)+'</div>',unsafe_allow_html=True)

elif page=='리밸런싱' and view is not None:
    st.caption('현재 비중: 🔴 목표 초과 · 🟢 목표와 같음 · 🔵 목표 미달 (소수점 둘째 자리 기준)')
    st.caption('SMA와 수익률: 완료된 월의 비수정 월말 종가 기준. 평가액은 원화 환산, 종가·SMA는 종목의 거래 통화입니다.')
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
            if view.value.isna().any():raise DataError('모든 종가·환율 조회를 완료하세요')
            old=st.session_state.snapshots;same=old.date.astype(str).eq(str(day))
            revisions=pd.to_numeric(old.get('revision',pd.Series(1,index=old.index)),errors='coerce').fillna(1)
            revision=int(revisions[same].max())+1 if same.any() else 1
            new=pd.DataFrame(dict(date=str(day),saved_at=pd.Timestamp.now(tz='UTC').isoformat(),strategy=view.strategy,account=view.account,ticker=view.ticker,name=view.name,category=view.category,close=view.close,shares=view.shares,value=view.value,weight_pct=view.total_weight,target_pct=view.target_pct,strategy_version='manual',memo=memo,revision=revision,fx=view.fx,price_date=view.price_date,account_weight_pct=view.weight))
            apply({'snapshots':pd.concat([old,new],ignore_index=True)},'평가를 기록했습니다. Sheets에 저장하세요.')
        except DataError as e:st.error(str(e))
    selected=st.selectbox('내보낼 시트',TABLES);table(st.session_state[selected]);st.code(to_tsv(st.session_state[selected]),language=None)
    st.download_button('CSV 다운로드',to_csv_bytes(st.session_state[selected]),selected+'.csv','text/csv')

elif page=='설정':
    tabs=st.tabs(['전략 관리','종목·수량·비중','원장·백업'])
    with tabs[0]:
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
    with tabs[1]:
        h=st.session_state.holdings;codes=h.strategy.drop_duplicates().tolist()
        if not codes:st.info('전략 관리에서 전략을 먼저 추가하세요.')
        else:
            code=st.selectbox('전략',codes,key='asset_strategy');sub=h[h.strategy.eq(code)].copy()
            st.caption('보유수량은 최종 잔고입니다. CASH 수량은 원화 현금 잔액입니다. 후보 종목은 수량 0으로 등록하세요.')
            labels={'ticker':'티커','name':'종목명','market':'시장','category':'자산 분류','shares':'보유수량','target_pct':'목표비중 (%)'}
            shown=sub[list(labels)].rename(columns=labels)
            with st.form('edit_assets'+code+str(st.session_state.revision)):
                edited=st.data_editor(shown,hide_index=True,use_container_width=True,disabled=['티커','시장'],column_config={'보유수량':st.column_config.NumberColumn(min_value=0.,format='%.4f'),'목표비중 (%)':st.column_config.NumberColumn(min_value=0.,max_value=100.,format='%.2f')})
                st.caption(f'현재 저장된 목표비중 합계 {sub.target_pct.sum():.2f}% · 합계 100%가 아니어도 작성 중인 계획을 저장할 수 있습니다.')
                if st.form_submit_button('보유수량·목표비중 적용'):
                    try:
                        updated=h.copy();updated.loc[sub.index,['name','category','shares','target_pct']]=edited[['종목명','자산 분류','보유수량','목표비중 (%)']].to_numpy()
                        st.session_state.demo=False;apply({'holdings':m.validate_holdings(updated)},'수량과 목표비중을 적용했습니다.')
                    except DataError as e:st.error(str(e))
            if abs(sub.target_pct.sum()-100)>.01:st.warning('목표비중 합계가 100%가 아닙니다. 리밸런싱 전에 조정하세요.')
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
    with tabs[2]:
        st.caption('기존 Apps Script 연결과 Sheets 저장·충돌 확인 방식은 유지됩니다.')
        if connected and st.button('최신 원장 미리보기'):
            try:st.session_state.preview=load_workspace(remote['SHEETS_WEBAPP_URL'],remote['SHEETS_SECRET'])
            except DataError as e:st.error(str(e))
        if st.session_state.get('preview'):
            data,token=st.session_state.preview;table(data['holdings'])
            if st.button('미리 본 원장 적용'):
                st.session_state.token=token;st.session_state.demo=False;data=st.session_state.pop('preview')[0];apply(data,'원장을 적용했습니다.')
        file=st.file_uploader('보유내역 CSV·TSV',type=['csv','tsv'])
        if file and st.button('보유내역 가져오기'):
            try:st.session_state.demo=False;apply({'holdings':m.validate_holdings(parse_table(file.getvalue()))},'보유내역을 가져왔습니다.')
            except DataError as e:st.error(str(e))
        backup=st.file_uploader('전체 백업 JSON',type=['json'])
        if backup and st.button('백업 복원'):
            try:st.session_state.demo=False;apply(restore_backup(backup.getvalue()),'백업을 복원했습니다.')
            except DataError as e:st.error(str(e))
