"""Design system 2.0 (2026-11-28): colors fixed to meaning, 억·만 amounts, and small HTML parts.

Colors come from the commissioned design. Stacking order was checked with the dataviz palette
validator so neighbouring pieces stay distinguishable; 현금 is gray and 신흥국 채권 pale on purpose,
so charts always carry a legend, 2px gaps and a value list.
"""
from html import escape
import math
import pandas as pd

BRAND='#3F46C8';UP='#E42939';DOWN='#2E6BE6';SAME='#12A16B';WARN='#E19A00';TEXT='#191F28';MUTED='#8B95A1'
# Strategy (account) colors; LAA→DAA and SSO→SPX keep their account's color, RESERVE is the cash account.
STRATEGY_COLORS={'GSM':'#7B5CF0','ISA':'#F08A24','LAA':'#12A38B','DAA':'#12A38B','GOLD':'#C9A227','SSO':'#13A6C9','SPX':'#13A6C9',
                 'EM':'#7F9228','KSP':'#D6458C','CASH':'#A7B0BC','RESERVE':'#A7B0BC'}
STRATEGY_ORDER=['GSM','ISA','LAA','DAA','GOLD','SSO','SPX','EM','KSP','CASH','RESERVE']  # validated stacking order
ASSET_COLORS={'선진국 주식':'#4A5FE0','금':'#C9A227','선진국 채권':'#9AABF4','신흥국 채권':'#F4B7A3','신흥국 주식':'#E06A4A','현금':'#A7B0BC'}
ASSET_ORDER=list(ASSET_COLORS)  # validated stacking order
OTHER='#C5CBD3'


def strategy_color(code):return STRATEGY_COLORS.get(str(code).upper(),OTHER)
def asset_color(category):return ASSET_COLORS.get(str(category),OTHER)


def won(value,unit=True):
    """3억 2,480만 / 8,412만 / 9,500원. Under 1만 is shown in 원; above, the 만 remainder is cut."""
    if value is None or pd.isna(value):return '—'
    v=float(value);sign='-' if v<0 else '';v=abs(v)
    if v<1e4:return f'{sign}{v:,.0f}원'
    eok,man=divmod(int(v//1e4),10000)
    text=(f'{eok}억 {man:,}만' if man else f'{eok}억') if eok else f'{man:,}만'
    return sign+text+('원' if unit else '')


def won_big(value):
    """Hero number: '3억 2,480' with a small '만원' tail."""
    if value is None or pd.isna(value):return '<strong class="ds-display">—</strong>'
    text=won(value,unit=False)
    if text.endswith('만'):return f'<strong class="ds-display">{escape(text[:-1])}<small>만원</small></strong>'
    if text.endswith('억'):return f'<strong class="ds-display">{escape(text)}<small>원</small></strong>'
    return f'<strong class="ds-display">{escape(text)}</strong>'


def change(now,before,label='',pct=True):
    """▲ 182만 (+0.56%) in red, ▼ in blue, — when unknown; label in gray in front."""
    head=f'<span class="ds-label">{escape(label)}</span> ' if label else ''
    if before is None or now is None or pd.isna(now) or pd.isna(before) or not before:return f'<span class="ds-chg flat">{head}—</span>'
    diff=float(now)-float(before);state='up' if diff>=5e3 else 'down' if diff<=-5e3 else 'flat'
    mark={'up':'▲','down':'▼','flat':''}[state]
    tail=f' ({diff/float(before)*100:+.2f}%)' if pct else ''
    return f'<span class="ds-chg {state}">{head}{mark} {won(abs(diff),unit=False) if state!="flat" else "0"}{tail}</span>'


def pct_change(pct):
    if pct is None or pd.isna(pct):return '<span class="ds-chg flat">—</span>'
    state='up' if pct>0.005 else 'down' if pct<-0.005 else 'flat'
    return f'<span class="ds-chg {state}">{"▲" if state=="up" else "▼" if state=="down" else ""} {abs(pct):.1f}%</span>'


def chip(code,label=None):
    return f'<span class="ds-chip" style="background:{strategy_color(code)}">{escape(label or str(code))}</span>'


def tag(text,kind='muted'):
    """Status chip: same (green) · warn (yellow) · bad (red) · brand · muted."""
    return f'<span class="ds-tag {kind}">{escape(text)}</span>'


def weight_text(current,target):
    """63.9% / 40% — the current number red over target, green within ±0.5%p, blue under."""
    if current is None or pd.isna(current):return '<span class="ds-w">—</span>'
    if target is None or pd.isna(target):return f'<span class="ds-w">{current:.1f}%</span>'
    state='same' if abs(current-target)<=.5 else 'over' if current>target else 'under'
    return f'<span class="ds-w {state}">{current:.1f}%</span><span class="ds-w-target"> / {target:g}%</span>'


def bar_row(name,sub,current,target,color):
    """Name, current/target text and a bar: fill = current (asset color), black tick = target."""
    fill=0 if current is None or pd.isna(current) else max(0,min(100,current))
    tick='' if target is None or pd.isna(target) else f'<i style="left:{max(0,min(100,target))}%"></i>'
    return (f'<div class="ds-bar-row"><div class="ds-bar-head"><span><b>{escape(name)}</b><small>{escape(sub)}</small></span>'
            f'<span>{weight_text(current,target)}</span></div><div class="ds-bar"><span style="width:{fill}%;background:{color}"></span>{tick}</div></div>')


def donut(parts,label,size=120):
    """CSS conic-gradient ring; parts = [(name, value, color)]. 2px white gaps between pieces."""
    total=sum(v for _,v,_ in parts if v and v>0)
    if total<=0:return f'<div class="ds-donut empty" style="width:{size}px;height:{size}px"><span>{escape(label)}</span></div>'
    stops=[];at=0.
    for _,v,color in parts:
        if not v or v<=0:continue
        share=v/total*360;gap=min(1.2,share/4)
        stops.append(f'{color} {at:.2f}deg {at+share-gap:.2f}deg, #fff {at+share-gap:.2f}deg {at+share:.2f}deg');at+=share
    return f'<div class="ds-donut" style="width:{size}px;height:{size}px;background:conic-gradient({", ".join(stops)})"><span>{escape(label)}</span></div>'


def legend(items):
    return '<div class="ds-legend">'+''.join(f'<span><i style="background:{c}"></i>{escape(n)}</span>' for n,c in items)+'</div>'


def order_line(side,name,shares,amount):
    """One-line rebalancing: ↓ 매도 41주 · 약 537만 (blue) / ↑ 매수 (red)."""
    kind='sell' if side=='매도' else 'buy'
    return (f'<div class="ds-order {kind}"><span class="ds-order-icon">{"↓" if kind=="sell" else "↑"}</span><b>{escape(name)}</b>'
            f'<span class="ds-order-act">{escape(side)} {shares:g}주 · 약 {won(amount,unit=False)}</span></div>')


def steps(current,names=('1 기준일','2 할 일','3 체결','4 마감')):
    """Progress bar of the four rebalancing steps; current is 1-based."""
    return '<div class="ds-steps">'+''.join(f'<div class="{"on" if i<=current else ""}"><i></i><span>{escape(n)}</span></div>' for i,n in enumerate(names,1))+'</div>'


def card(body,cls=''):
    return f'<section class="ds-card {cls}">{body}</section>'
