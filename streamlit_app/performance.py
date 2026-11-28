"""Principal and returns from the 입출금 tab (cashflows): deposits are +, withdrawals −, in won.

No screen code here on purpose: where these numbers appear waits for the design (2026-11-28).
"""
from datetime import date
import math
import pandas as pd
from streamlit_app.data import DataError


def add_cashflow(cashflows,holdings,day,account,amount,memo=''):
    """Append one 입출금 row; the strategy code is looked up from the account name."""
    try:amount=float(amount)
    except (TypeError,ValueError):raise DataError('금액에 숫자를 입력하세요')
    if not math.isfinite(amount) or amount==0:raise DataError('금액은 0이 아닌 숫자여야 합니다 (입금 +, 출금 −)')
    codes=holdings.loc[holdings.account.eq(account),'strategy'].drop_duplicates().tolist()
    if not codes:raise DataError('보유 탭에 없는 계좌입니다')
    row=dict(date=str(day),account=account,amount=round(amount),memo=str(memo or ''),strategy=codes[0],kind='입금' if amount>0 else '출금')
    return pd.concat([cashflows,pd.DataFrame([row])],ignore_index=True)


def flows(cashflows,codes=None,upto=None):
    """[(date, amount)] sorted by date, optionally for some strategy codes and up to a day (inclusive)."""
    if cashflows is None or cashflows.empty or 'amount' not in cashflows:return []
    f=cashflows.copy();f['date']=pd.to_datetime(f.date,errors='coerce');f['amount']=pd.to_numeric(f.amount,errors='coerce')
    f=f[f.date.notna()&f.amount.notna()]
    if codes is not None:f=f[f.strategy.astype(str).isin(set(codes))]
    if upto is not None:f=f[f.date<=pd.Timestamp(upto)]
    return [(d.date(),float(a)) for d,a in f.sort_values('date')[['date','amount']].itertuples(index=False)]


def net_flow(cashflows,after,upto,codes=None):
    """Money put in minus taken out with after < date <= upto (to strip deposits from a change)."""
    return sum(a for d,a in flows(cashflows,codes,upto) if d>pd.Timestamp(after).date())


def xirr(cash,value,day):
    """Money-weighted yearly return: what rate makes the deposits grow into today's value. None if undefined."""
    if not cash or value is None or not math.isfinite(value):return None
    def npv(r):return value-sum(a*(1+r)**((day-d).days/365) for d,a in cash)  # deposits grown at r vs value now
    lo,hi=-.99,10.
    if npv(lo)*npv(hi)>0:return None
    for _ in range(200):
        mid=(lo+hi)/2
        if npv(lo)*npv(mid)<=0:hi=mid
        else:lo=mid
    return (lo+hi)/2*100


def summary(value,cashflows,day,codes=None,min_days=365):
    """원금(net deposits), 총 수익, 총 수익률, 연환산 수익률 (only once the first deposit is min_days old)."""
    cash=flows(cashflows,codes,day)
    if not cash:return None
    principal=sum(a for _,a in cash)
    out=dict(principal=principal,profit=value-principal,return_pct=(value/principal-1)*100 if principal>0 else None,
             since=cash[0][0],annual_pct=None)
    if (day-cash[0][0]).days>=min_days:out['annual_pct']=xirr(cash,value,day)
    return out
