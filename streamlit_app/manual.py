"""Manual portfolio operations; no automatic strategy evaluation."""
from datetime import timedelta
import math
import uuid
import pandas as pd
from streamlit_app.data import DataError, normalize_holdings, normalize_strategies


def market_of(ticker,market='KR'):
    t=str(ticker).strip().upper()
    if t=='CASH' or t.endswith(('.KS','.KQ')):return 'KR'
    return 'US' if any(c.isalpha() for c in t) else market


def symbol(ticker,market):
    t=str(ticker).strip().upper()
    return t.zfill(6)+'.KS' if market_of(t,market)=='KR' and t.isdigit() else t


def canonical(ticker,market):
    t=str(ticker).strip().upper()
    if not t:raise DataError('티커를 입력하세요')
    if market=='KR' and t.endswith('.KS'):t=t[:-3]
    if market=='KR' and t.isdigit():t=t.zfill(6)
    return t


def number(value,label,maximum=None):
    try:v=float(value)
    except (TypeError,ValueError):raise DataError(label+'에 숫자를 입력하세요')
    if not math.isfinite(v) or v<0 or (maximum is not None and v>maximum):raise DataError(label+'의 범위를 확인하세요')
    return v


def validate_holdings(frame):
    h=normalize_holdings(frame)
    for r in h.itertuples():
        if r.ticker!='CASH' and market_of(r.ticker,r.market)=='KR' and float(r.shares)%1:
            raise DataError('국내 종목의 보유수량은 정수여야 합니다')
    return h


def add_strategy(w,code,account,description=''):
    code=code.strip();account=account.strip()
    if not code or not account:raise DataError('전략명과 계좌명을 입력하세요')
    if code in set(w['strategies'].code)|set(w['holdings'].strategy):raise DataError('이미 존재하는 전략명입니다')
    out={k:v.copy() for k,v in w.items()}
    row={'code':code,'account':account,'description':description,'rule':'manual','params_json':'{}'}
    out['strategies']=normalize_strategies(pd.concat([out['strategies'],pd.DataFrame([row])],ignore_index=True))
    cash=dict(strategy=code,account=account,ticker='CASH',name='현금',market='KR',category='현금',role='현금',target_pct=100.,shares=0.)
    out['holdings']=validate_holdings(pd.concat([out['holdings'],pd.DataFrame([cash])],ignore_index=True))
    return out


def change_strategy(w,old,new,account,description):
    new=new.strip();account=account.strip()
    if not new or not account:raise DataError('전략명과 계좌명을 입력하세요')
    if new!=old and new in set(w['strategies'].code)|set(w['holdings'].strategy):raise DataError('이미 존재하는 전략명입니다')
    out={k:v.copy() for k,v in w.items()}
    mask=out['holdings'].strategy.eq(old);out['holdings'].loc[mask,['strategy','account']]=[new,account]
    mask=out['strategies'].code.eq(old)
    if mask.any():out['strategies'].loc[mask,['code','account','description']]=[new,account,description]
    else:
        out['strategies']=pd.concat([out['strategies'],pd.DataFrame([dict(code=new,account=account,description=description,rule='manual',params_json='{}')])],ignore_index=True)
    out['strategies']=normalize_strategies(out['strategies']);out['holdings']=validate_holdings(out['holdings'])
    return out


def delete_strategy(w,code):
    if w['holdings'].loc[w['holdings'].strategy.eq(code),'shares'].sum()>0:raise DataError('보유 자산이 있습니다. 수량과 현금 잔액을 0으로 정리한 뒤 삭제하세요')
    out={k:v.copy() for k,v in w.items()}
    out['holdings']=out['holdings'][~out['holdings'].strategy.eq(code)].reset_index(drop=True)
    out['strategies']=out['strategies'][~out['strategies'].code.eq(code)].reset_index(drop=True)
    return out


def add_asset(h,code,asset,shares=0.,target=0.):
    h=validate_holdings(h);sub=h[h.strategy.eq(code)]
    if sub.empty:raise DataError('전략을 먼저 추가하세요')
    market=market_of(asset['ticker'],asset.get('market','KR'));ticker=canonical(asset['ticker'],market)
    if (sub.ticker==ticker).any():raise DataError('이미 등록된 종목입니다. 보유수량 표에서 수정하세요')
    row=dict(strategy=code,account=sub.account.iloc[0],ticker=ticker,name=asset.get('name') or ticker,
        market=market,category=asset.get('category') or '미분류',role='',shares=number(shares,'보유수량'),target_pct=number(target,'목표비중',100))
    return validate_holdings(pd.concat([h,pd.DataFrame([row])],ignore_index=True))


def delete_asset(h,code,ticker):
    mask=h.strategy.eq(code)&h.ticker.eq(ticker)
    if not mask.any():raise DataError('종목이 없습니다')
    if ticker=='CASH':raise DataError('현금 항목은 삭제할 수 없습니다')
    if float(h.loc[mask,'shares'].iloc[0])>0:raise DataError('보유수량을 0으로 정리한 뒤 삭제하세요')
    return h[~mask].reset_index(drop=True)


def adjust(h,code,ticker,quantity,side):
    q=number(quantity,'매매수량')
    if q==0:raise DataError('매매수량은 0보다 커야 합니다')
    if side not in ['매수','매도']:raise DataError('매수 또는 매도를 선택하세요')
    mask=h.strategy.eq(code)&h.ticker.eq(ticker)
    if not mask.any() or ticker=='CASH':raise DataError('매매할 종목을 먼저 등록하세요')
    out=h.copy();before=float(out.loc[mask,'shares'].iloc[0]);after=before+(q if side=='매수' else -q)
    if after<0:raise DataError('보유수량보다 많이 매도할 수 없습니다')
    out.loc[mask,'shares']=after
    return validate_holdings(out),before,after


def fetch_prices(ticker,market,day):
    import yfinance as yf
    d=yf.download(symbol(ticker,market),start=day-timedelta(days=1600),end=day+timedelta(days=1),auto_adjust=False,progress=False,threads=False)
    if d.empty:return pd.Series(dtype=float)
    s=d['Close'];return s.iloc[:,0] if isinstance(s,pd.DataFrame) else s


# Common portfolio ETFs remain discoverable when the remote search service is unavailable.
BUILTIN_ASSETS=[
    dict(ticker='QQQ',name='Invesco QQQ Trust',market='US'),
    dict(ticker='SPY',name='SPDR S&P 500 ETF Trust',market='US'),
    dict(ticker='SSO',name='ProShares Ultra S&P500',market='US'),
    dict(ticker='QLD',name='ProShares Ultra QQQ',market='US'),
    dict(ticker='TQQQ',name='ProShares UltraPro QQQ',market='US'),
    dict(ticker='360750',name='TIGER 미국S&P500',market='KR'),
    dict(ticker='069500',name='KODEX 200',market='KR'),
    dict(ticker='245350',name='TIGER 유로스탁스배당30',market='KR'),
    dict(ticker='251350',name='KODEX 선진국MSCI World',market='KR'),
]

def search(query,market,mode='auto'):
    import re
    import yfinance as yf
    query=query.strip()
    if not query:return []
    ticker_query=bool(re.fullmatch(r'[A-Za-z][A-Za-z0-9.\-]{0,14}',query)) and mode!='name'
    if ticker_query:market='US'
    elif query.isdigit() and mode!='name':market='KR'
    fallback=[dict(r,source='기본 종목 목록') for r in BUILTIN_ASSETS
              if r['market']==market and (query.casefold() in r['ticker'].casefold() or query.casefold() in r['name'].casefold())]
    results=[]
    errors=[];successful_sources=0
    if market=='KR':
        try:
            import FinanceDataReader as fdr
            for listing_name in ['ETF/KR','KRX']:
                try:
                    listing=fdr.StockListing(listing_name)
                    if listing.empty:raise ValueError('empty listing')
                    code_column='Code' if 'Code' in listing else 'Symbol'
                    codes=listing[code_column].astype(str).str.replace(r'\.0$','',regex=True).str.zfill(6)
                    names=listing['Name'].astype(str)
                    hits=listing.loc[names.str.contains(query,case=False,regex=False)|codes.str.contains(query,regex=False)].copy()
                    hits['_code']=codes.loc[hits.index]
                    results += [dict(ticker=r['_code'],name=str(r['Name']),market='KR',source=listing_name) for r in hits.head(20).to_dict('records')]
                    successful_sources+=1
                except Exception:errors.append(listing_name+' 목록 조회 실패')
        except ImportError:errors.append('국내 종목 검색 패키지 설치 누락')
    else:
        # Direct symbol lookup is independent of the Yahoo text search endpoint.
        if ticker_query:
            try:
                info=yf.Ticker(query.upper()).info
                if info.get('shortName') or info.get('longName'):
                    results.append(dict(ticker=query.upper(),name=info.get('shortName') or info['longName'],market='US',source='티커 정보 조회'))
                    successful_sources+=1
            except Exception:errors.append('티커 정보 조회 제한 또는 연결 실패')
    try:
        quotes=yf.Search(query,max_results=20,timeout=8).quotes
        successful_sources+=1
        results += [dict(ticker=canonical(q['symbol'],market),name=q.get('shortname') or q.get('longname') or q['symbol'],market=market,source='Yahoo 검색')
                    for q in quotes if q.get('symbol') and market_of(q['symbol'],market)==market]
    except Exception:errors.append('Yahoo 검색 요청 제한 또는 연결 실패')
    results += fallback
    if ticker_query and not any(r['ticker']==query.upper() for r in results):
        results.append(dict(ticker=query.upper(),name=query.upper(),market='US',source='입력 티커 · 종목 정보 미확인',unverified=True,
                            search_warning='외부 서비스에서 종목 정보를 확인하지 못했습니다. 입력한 티커로 등록할 수 있지만, 종가 조회 성공을 확인해야 합니다.'))
    unique={}
    for r in results:unique.setdefault(r['ticker'],r)
    output=sorted(unique.values(),key=lambda r:(r['ticker']!=query.upper(),r['ticker']))
    if not output and errors:
        raise DataError(' · '.join(errors)+' — 종목이 없다는 뜻은 아닙니다. 다시 검색하거나 티커를 직접 입력하세요.')
    if errors:
        for r in output:
            if not r.get('unverified'):r['search_warning']='일부 검색 서비스 조회에 실패했습니다. 기본 목록 또는 조회에 성공한 결과만 표시합니다.'
    return output[:40]


def clean(s,day):
    s=pd.to_numeric(s,errors='coerce').dropna();s.index=pd.to_datetime(s.index,utc=True).tz_localize(None).normalize()
    s=s.loc[s.index<=pd.Timestamp(day)].sort_index();s=s[~s.index.duplicated(keep='last')]
    if s.empty or not s.map(math.isfinite).all() or (s<=0).any():raise DataError('유효한 종가가 없습니다')
    if (pd.Timestamp(day)-s.index[-1]).days>7:raise DataError('마지막 가격일이 7일 이상 오래되었습니다')
    return s


def valuation(h,day,fetch=fetch_prices):
    v=validate_holdings(h).copy();errors=[];cache={}
    for c in ['close','fx','sma10','return12','value','weight','total_weight']:v[c]=float('nan')
    v['price_date']=''
    def get(t,m):
        if (t,m) not in cache:cache[t,m]=clean(fetch(t,m,day),day)
        return cache[t,m]
    for idx,r in v.iterrows():
        try:
            if r.ticker=='CASH':close=fx=1.;price_date=str(day)
            else:
                market=market_of(r.ticker,r.market);s=get(r.ticker,market);close=float(s.iloc[-1]);price_date=str(s.index[-1].date())
                fx=float(get('KRW=X','US').iloc[-1]) if market=='US' else 1.
                months=s.resample('ME').last().dropna();months=months[months.index<=pd.Timestamp(day)]
                if len(months)>=10:v.at[idx,'sma10']=float(months.tail(10).mean())
                if len(months)>=13:v.at[idx,'return12']=float(months.iloc[-1]/months.iloc[-13]-1)*100
            v.loc[idx,['close','fx','value','price_date']]=[close,fx,float(r.shares)*close*fx,price_date]
        except Exception as e:errors.append(f'{r.strategy} · {r.ticker}: {e}')
    for code,ids in v.groupby('strategy').groups.items():
        sub=v.loc[ids,'value']
        if sub.notna().all():v.loc[ids,'weight']=sub/sub.sum()*100 if sub.sum() else 0.
    if v.value.notna().all():v['total_weight']=v.value/v.value.sum()*100 if v.value.sum() else 0.
    return v,errors


def action(h,code,ticker,q,side,day,before,after):
    r=h.loc[h.strategy.eq(code)&h.ticker.eq(ticker)].iloc[0]
    return dict(date=str(day),saved_at=pd.Timestamp.now(tz='UTC').isoformat(),strategy=code,ticker=ticker,name=r['name'],side=side,
        planned_shares=q if side=='매수' else -q,actual_shares=q,planned_amount=None,done=True,reason='수동 수량 조정',memo=f'{before:g} → {after:g}',
        execution_id=uuid.uuid4().hex,execution_date=str(day),actual_price=None,actual_amount=None,status='완료',currency='USD' if r.market=='US' else 'KRW')


def revalue(view,holdings):
    """Recalculate quantities using the exact quotes already displayed to the user."""
    h=validate_holdings(holdings)
    keys=['strategy','ticker']
    quotes=view.set_index(keys)
    if any(tuple(r) not in quotes.index for r in h[keys].itertuples(index=False,name=None)):
        raise DataError('새 종목의 종가를 먼저 조회하세요')
    v=h.merge(view[keys+['close','fx','sma10','return12','price_date']],on=keys,how='left',validate='one_to_one')
    v['value']=v.shares*v.close*v.fx;v['weight']=float('nan');v['total_weight']=float('nan')
    for _,ids in v.groupby('strategy').groups.items():
        values=v.loc[ids,'value']
        if values.notna().all():v.loc[ids,'weight']=values/values.sum()*100 if values.sum() else 0.
    if v.value.notna().all():v['total_weight']=v.value/v.value.sum()*100 if v.value.sum() else 0.
    return v


def category_distribution(view):
    if view.value.isna().any():raise DataError('모든 종가와 환율을 조회한 뒤 분류별 분포를 확인하세요')
    return view.groupby('category',as_index=False)['value'].sum().loc[lambda x:x.value>0].sort_values('value',ascending=False)
