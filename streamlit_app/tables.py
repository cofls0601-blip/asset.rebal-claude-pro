"""Responsive read-only portfolio table; editing uses native validated controls."""
from html import escape
import pandas as pd


def num(value,digits=2,suffix=''):
    if pd.isna(value):return '—'
    return f'{float(value):,.{digits}f}'+suffix


def weight_html(current, target):
    """Compare at the same two-decimal precision used on screen."""
    shown = num(current, 2, '%')
    if pd.isna(current) or pd.isna(target):
        return f'<span class="weight-neutral">{shown}</span>'
    current, target = float(f'{float(current):.2f}'), float(f'{float(target):.2f}')
    state = 'over' if current > target else 'under' if current < target else 'equal'
    label = {'over': '목표보다 높음', 'under': '목표보다 낮음', 'equal': '목표와 같음'}[state]
    return f'<span class="weight-{state}" title="{label}">{shown}</span>'


def portfolio_table(view):
    headers=['전략명','티커','종목명','보유 수량','원화/달러','종가','10개월 SMA','평가액','현재 비중','목표 비중','12개월 수익률']
    widths=[5,6,14,8,6,10,10,14,8,8,11]
    columns='<colgroup>'+''.join(f'<col style="width:{width}%">' for width in widths)+'</colgroup>'
    rows=[];cards=[]
    for r in view.to_dict('records'):
        name=escape(str(r['name']));ticker=escape(str(r['ticker']));code=escape(str(r['strategy']))
        currency='달러' if r['market']=='US' else '원화'
        price_digits=2 if r['market']=='US' else 0
        qty=num(r['shares'],4).rstrip('0').rstrip('.')
        gain=r['return12'];gain_class='positive' if pd.notna(gain) and gain>0 else 'negative' if pd.notna(gain) and gain<0 else ''
        weight=weight_html(r['weight'],r['target_pct'])
        values=[code,f'<span class="ticker">{ticker}</span>',f'<span class="security-name">{name}</span>',qty,currency,num(r['close'],price_digits),num(r['sma10'],price_digits),num(r['value'],0),weight,num(r['target_pct'],2,'%'),f'<span class="{gain_class}">{num(gain,2,"%")}</span>']
        rows.append('<tr>'+''.join(f'<td class="{"numeric" if i>=3 and i!=4 else ""}">{v}</td>' for i,v in enumerate(values))+'</tr>')
        fields=[('보유수량',qty+'주'),('통화',currency),('종가',num(r['close'],price_digits)),('10개월 SMA',num(r['sma10'],price_digits)),('현재 비중',weight),('목표 비중',num(r['target_pct'],2,'%')),('12개월 수익률',num(gain,2,'%'))]
        cards.append(f'<article class="holding-detail"><div class="detail-head"><div><b>{name}</b><small>{ticker} · {code}</small></div><div class="detail-value"><small>평가액</small><b>{num(r["value"],0)}원</b></div></div><dl>'+''.join(f'<div><dt>{label}</dt><dd>{value}</dd></div>' for label,value in fields)+'</dl></article>')
    return '<div class="portfolio-desktop"><div class="portfolio-table-scroll"><table class="portfolio-table">'+columns+'<thead><tr>'+''.join(f'<th class="{"numeric" if i>=3 and i!=4 else ""}">{h}</th>' for i,h in enumerate(headers))+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div><div class="table-footnote">평가액은 원화 환산 · 종가와 SMA는 표시 통화 기준 · 목표 비중은 아래에서 수정</div></div><div class="portfolio-mobile">'+''.join(cards)+'</div>'
