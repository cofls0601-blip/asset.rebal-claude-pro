"""백테스트할 전략들.

자산 이름은 미국 상장 ETF 기준 대용치다(국내 ETF는 같은 지수를 따르므로 원화 환산만 다르다).
  NDX=나스닥100(QQQ), SPX=S&P500(SPY), WORLD=MSCI World(URTH), EURO=유로스톡스50(FEZ),
  GOLD=금(GLD), UST10=미국 7-10년 국채(IEF), CASH=미국 3개월 국채(^IRX) 등.

현재 전략 4개(GSM·LAA·SSO·ISA)는 streamlit_app/rules.py와 같은 판정을 한다.
"""
from __future__ import annotations

import numpy as np

from backtest.engine import CASH, Context

QUARTER_MONTHS = (3, 6, 9, 12)


def hold(weights: dict, months: tuple[int, ...] | None = None):
    """고정 비중. months가 있으면 그 달에만 복원하고 나머지 달은 그대로 둔다."""
    def strat(d, ctx: Context):
        if months is None or d.month in months or ctx.i == 0 or not ctx.state.get("started"):
            ctx.state["started"] = True
            return dict(weights)
        return None
    return strat


# ---------------------------------------------------------------- 현재 전략

def gsm(cands=("NDX", "SPX", "WORLD", "EURO"), invest=0.8, safe=CASH, mom="12m", top=1, sma_n=10):
    """SMA 위 후보 중 모멘텀 1위에 invest, 나머지는 safe. 모두 SMA 아래면 safe 100%."""
    def strat(d, ctx: Context):
        m = ctx.m
        sma = m.sma(sma_n)
        score = _score(m, mom)
        ok = [c for c in cands if ctx.val(m.close, c) > ctx.val(sma, c)]
        if not ok:
            return {safe: 1.0}
        ranked = sorted(ok, key=lambda c: (-ctx.val(score, c), c))[:top]
        w = {c: invest / len(ranked) for c in ranked}
        w[safe] = w.get(safe, 0) + 1 - invest
        return w
    return strat


LAA_TARGET = {"NDX": .125, "EURO": .125, "SPX": .125, "WORLD": .125, "GOLD": .25, "UST10": .25}


def laa_variant(target=None, filters=("NDX", "EURO"), restore=QUARTER_MONTHS, safe=CASH, rebuy=False):
    """사용자 변형 LAA. 필터 종목이 SMA 아래면 그 비중을 현금으로. 복원은 restore 달에만.

    rebuy=True면 분기 사이라도 필터가 다시 SMA 위로 오면 바로 되산다(개선안 비교용).
    """
    target = dict(target or LAA_TARGET)

    def strat(d, ctx: Context):
        m = ctx.m
        sma = m.sma(10)
        below = {f for f in filters if ctx.val(m.close, f) < ctx.val(sma, f)}
        first = not ctx.state.get("started")
        ctx.state["started"] = True
        if first or d.month in restore:
            base = dict(target)
        else:
            base = dict(ctx.weights)
            if rebuy:
                for f in filters:
                    if f not in below and base.get(f, 0) < 1e-9 and base.get(safe, 0) >= target[f] - 1e-9:
                        base[f] = target[f]
                        base[safe] -= target[f]
        for f in below:
            base[safe] = base.get(safe, 0) + base.get(f, 0)
            base[f] = 0.0
        return base
    return strat


SSO_STEPS = [(-.15, .85), (-.20, .925)]
ISA_STEPS = [(-.10, 1 / 3), (-.15, 2 / 3), (-.20, 1.0)]
STEP_TOLERANCE = .05


def ladder(asset, signal, base, steps, safe=CASH, tolerance=STEP_TOLERANCE, recover=0.0, sma_exit=False,
           sma_sell=False, stop=None):
    """52주 고점 대비 하락 단계 매수 (rules.check_ladder와 같음).

    recover: 고점 대비 이 값 이상이면 '회복'으로 보고 기본 비중으로 돌아간다(0=신고가).
    sma_exit: True면 신호 지수가 10개월 SMA 아래일 때 기본 비중보다 더 사지 않는다(개선안).
    sma_sell: True면 신호 지수가 10개월 SMA 아래일 때 기본 비중으로 되돌린다(개선안).
    stop: 고점 대비 이 값 이하로 더 빠지면 기본 비중으로 되돌린다(손절, 개선안).
    """
    def strat(d, ctx: Context):
        m = ctx.m
        dd = ctx.val(m.drawdown52(), signal)
        w = ctx.weights.get(asset, 0.0)
        plan = lambda x: {asset: x, safe: 1 - x}
        if not ctx.state.get("started"):
            ctx.state["started"] = True
            return plan(base)
        if dd >= recover - 1e-12:
            return plan(base)
        reached = [x for lim, x in steps if dd <= lim]
        below_sma = ctx.val(m.close, signal) < ctx.val(m.sma(10), signal)
        if (sma_sell and below_sma) or (stop is not None and dd <= stop):
            return plan(base)
        if sma_exit and below_sma:
            reached = []
        if reached and w < max(reached) - tolerance:
            return plan(max(reached))
        return None
    return strat


# ---------------------------------------------------------------- 잘 알려진 전략(비교용)

def gtaa(assets=("SPX", "EFA", "UST10", "DBC", "REIT"), safe=CASH):
    """Faber GTAA 5: 각 20%, 10개월 SMA 아래면 그 몫은 현금."""
    def strat(d, ctx):
        m = ctx.m
        sma = m.sma(10)
        w = {}
        for a in assets:
            k = a if ctx.val(m.close, a) > ctx.val(sma, a) else safe
            w[k] = w.get(k, 0) + 1 / len(assets)
        return w
    return strat


def dual_momentum(risk=("SPX", "EFA"), bond="AGG"):
    """Antonacci GEM: S&P500 12개월이 현금보다 높으면 미국·선진국 중 강한 쪽, 아니면 채권."""
    def strat(d, ctx):
        mo = ctx.m.mom_total(12)
        if ctx.val(mo, "SPX") > ctx.val(mo, CASH):
            return {max(risk, key=lambda a: ctx.val(mo, a)): 1.0}
        return {bond: 1.0}
    return strat


def vaa(offense=("SPX", "EFA", "EEM", "AGG"), defense=("LQD", "UST10", "SHY")):
    """Keller VAA-G4: 공격 자산 13612W가 모두 양수면 공격 1위, 아니면 방어 1위."""
    def strat(d, ctx):
        s = ctx.m.w13612()
        if all(ctx.val(s, a) > 0 for a in offense):
            return {max(offense, key=lambda a: ctx.val(s, a)): 1.0}
        return {max(defense, key=lambda a: ctx.val(s, a)): 1.0}
    return strat


def daa(offense=("SPX", "IWM", "NDX", "EFA", "EWJ", "EEM", "REIT", "DBC", "GOLD", "TLT", "HYG", "LQD"),
        canary=("EEM", "AGG"), defense=("SHY", "UST10", "LQD"), top=6):
    """Keller DAA-G12: 카나리아(EEM·AGG) 음수 개수로 공격 비중 100/50/0%."""
    def strat(d, ctx):
        s = ctx.m.w13612()
        bad = sum(ctx.val(s, c) <= 0 for c in canary)
        off = 1 - bad / len(canary)
        w = {}
        if off > 0:
            for a in sorted(offense, key=lambda a: -ctx.val(s, a))[:top]:
                w[a] = off / top
        if off < 1:
            b = max(defense, key=lambda a: ctx.val(s, a))
            w[b] = w.get(b, 0) + 1 - off
        return w
    return strat


def haa(offense=("SPX", "IWM", "EFA", "EEM", "REIT", "DBC", "UST10", "TLT"), canary="TIP", top=4):
    """Keller HAA: TIP 모멘텀이 양수면 공격 상위 4(음수면 그 몫은 현금), 아니면 IEF/현금 중 강한 쪽."""
    def strat(d, ctx):
        m = ctx.m
        s = (m.mom_total(1) + m.mom_total(3) + m.mom_total(6) + m.mom_total(12)) / 4
        safe = max(("UST10", CASH), key=lambda a: ctx.val(s, a))
        if ctx.val(s, canary) <= 0:
            return {safe: 1.0}
        w = {}
        for a in sorted(offense, key=lambda a: -ctx.val(s, a))[:top]:
            k = a if ctx.val(s, a) > 0 else safe
            w[k] = w.get(k, 0) + 1 / top
        return w
    return strat


def baa(offense=("SPX", "NDX", "IWM", "EFA", "EWJ", "EEM", "REIT", "DBC", "GOLD", "TLT", "HYG", "LQD"),
        canary=("SPX", "EFA", "EEM", "AGG"), defense=("TIP", "DBC", CASH, "UST10", "TLT", "LQD", "AGG"),
        top_off=6, top_def=3):
    """Keller BAA-G12(균형형): 카나리아 하나라도 음수면 방어 상위 3(현금보다 약하면 현금)."""
    def strat(d, ctx):
        m = ctx.m
        s = m.w13612()
        rel = m.total / m.total.rolling(13).mean() - 1
        if all(ctx.val(s, c) > 0 for c in canary):
            pick = sorted(offense, key=lambda a: -ctx.val(rel, a))[:top_off]
            return {a: 1 / top_off for a in pick}
        pick = sorted(defense, key=lambda a: -ctx.val(rel, a))[:top_def]
        w = {}
        for a in pick:
            k = a if ctx.val(rel, a) >= ctx.val(rel, CASH) else CASH
            w[k] = w.get(k, 0) + 1 / top_def
        return w
    return strat


def laa_original(timing="SPX"):
    """Keller 원조 LAA(실업률 조건은 자료가 없어 뺌): 가치주·금·중기채 25%씩 고정,
    나머지 25%는 S&P500이 10개월 SMA 위면 나스닥, 아래면 단기채. 고정 몫은 연 1회 복원."""
    def strat(d, ctx):
        m = ctx.m
        sw = "NDX" if ctx.val(m.close, timing) > ctx.val(m.sma(10), timing) else "SHY"
        return {"SPX": .25, "GOLD": .25, "UST10": .25, sw: .25}
    return strat


def adm(risk=("SPX", "EFA"), bond="TLT"):
    """가속 듀얼 모멘텀: 1·3·6개월 수익률 합이 큰 쪽, 둘 다 음수면 장기채."""
    def strat(d, ctx):
        m = ctx.m
        s = m.mom_total(1) + m.mom_total(3) + m.mom_total(6)
        best = max(risk, key=lambda a: ctx.val(s, a))
        return {best: 1.0} if ctx.val(s, best) > 0 else {bond: 1.0}
    return strat


def relative_momentum(cands=("KOSPI", "SPX"), safe=CASH, months=12, score=None):
    """후보 중 수익률이 가장 높은 하나에 100%. 그것도 현금보다 낮으면 safe 100%.

    score: None이면 months개월 총수익률, "13612w"면 가중 모멘텀.
    """
    def strat(d, ctx):
        m = ctx.m
        s = m.w13612() if score == "13612w" else m.mom_total(months)
        best = max(cands, key=lambda a: ctx.val(s, a))
        ref = 0.0 if score == "13612w" else ctx.val(s, safe)
        return {best: 1.0} if ctx.val(s, best) > ref else {safe: 1.0}
    return strat


def mix(stocks: dict, stock_share: float, filter_asset=None, keep_below=1.0, months=(12,)):
    """종목 비율(stocks)을 주식 몫(stock_share)만큼, 나머지는 현금. months에 비율 복원.

    filter_asset이 10개월 SMA 아래면 주식 몫을 keep_below배로 줄인다(바뀌는 달에 매매).
    """
    total = sum(stocks.values())
    norm = {k: v / total for k, v in stocks.items()}

    def strat(d, ctx):
        below = filter_asset is not None and ctx.val(ctx.m.close, filter_asset) < ctx.val(ctx.m.sma(10), filter_asset)
        prev = ctx.state.get("below")
        ctx.state["below"] = below
        first = not ctx.state.get("started")
        ctx.state["started"] = True
        if first or d.month in months or below != prev:
            s = stock_share * (keep_below if below else 1.0)
            w = {k: s * v for k, v in norm.items()}
            w[CASH] = w.get(CASH, 0) + 1 - s
            return w
        return None
    return strat


def _score(m, kind):
    if kind == "12m":
        return m.mom(12)
    if kind == "13612w":
        return m.w13612()
    if kind == "6m":
        return m.mom(6)
    if kind == "avg":
        return (m.mom(1) + m.mom(3) + m.mom(6) + m.mom(12)) / 4
    raise ValueError(kind)


__all__ = [n for n in dir() if not n.startswith("_") and n != "np"]
