"""Turn target weights into share orders for one account (docs/새 설계안.md).

Sells come first; buys are paid from the account's cash plus the sell proceeds. When that
money is not enough, buy quantities are cut and the cut is reported. Prices are the
quotes already loaded (close × fx in KRW); fees and taxes are ignored.
"""
import math
import pandas as pd
from streamlit_app.manual import adjust


def plan_orders(sub,targets,fractional_us=False):
    """sub: valued rows of one strategy; targets: {ticker: weight %}. Returns (orders, notes)."""
    total=float(sub.value.sum());cash=float(sub.loc[sub.ticker.eq('CASH'),'value'].sum())
    rows={r.ticker:r for r in sub.itertuples() if r.ticker!='CASH'}
    def step(r):return 1e-4 if fractional_us and r.market=='US' else 1.
    def floor(q,r):s=step(r);return math.floor(q/s+1e-9)*s
    orders=[];notes=[]
    for t,r in rows.items():
        want=total*targets.get(t,0.)/100;price=float(r.close)*float(r.fx)
        if want<float(r.value)-price/2:
            q=float(r.shares) if targets.get(t,0.)<=0 else floor((float(r.value)-want)/price,r)
            if q>0:orders.append(dict(ticker=t,name=r.name,side='매도',shares=q,price=price,amount=q*price,cut=0.))
    budget=cash+sum(o['amount'] for o in orders)
    buys=[]
    for t,r in rows.items():
        price=float(r.close)*float(r.fx);q=floor((total*targets.get(t,0.)/100-float(r.value))/price,r)
        if q>0:buys.append(dict(ticker=t,name=r.name,side='매수',shares=q,price=price,amount=q*price,cut=0.))
    # Largest purchase is trimmed first so smaller positions still get bought.
    for o in sorted(buys,key=lambda o:-o['amount']):
        need=sum(b['amount'] for b in buys)-budget
        if need<=1e-6:break
        r=rows[o['ticker']];less=min(o['shares'],math.ceil(need/o['price']/step(r))*step(r))
        o['shares']-=less;o['cut']+=less;o['amount']=o['shares']*o['price']
    for o in buys:
        if o['cut']:notes.append(f'{o["name"]}: 현금 부족으로 {o["cut"]:g}주 줄임')
    orders+=[o for o in buys if o['shares']>0]
    return orders,notes


def orders_frame(orders):
    return pd.DataFrame([{'구분':o['side'],'종목':o['name'],'수량':o['shares'],'예상 금액':round(o['amount'])} for o in orders],
                        columns=['구분','종목','수량','예상 금액'])


def apply_fill(holdings,code,ticker,side,shares,price):
    """Add or remove filled shares and move the estimated amount through the account's CASH row."""
    out,before,after=adjust(holdings,code,ticker,shares,side)
    cash=out.strategy.eq(code)&out.ticker.eq('CASH')
    if cash.any():
        amount=float(shares)*float(price)
        out.loc[cash,'shares']=max(0.,float(out.loc[cash,'shares'].iloc[0])+(amount if side=='매도' else -amount))
    return out,before,after
