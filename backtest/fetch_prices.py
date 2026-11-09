"""백테스트용 공개 시세 내려받기 (GitHub Actions에서 실행).

이 컨테이너에서는 Yahoo 접속이 막혀 있어서, GitHub Actions가 대신 받아
backtest/data/ 에 저장한다. 개인 자료는 없고 공개 시세만 담는다.

    python backtest/fetch_prices.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

DATA_DIR = Path(__file__).resolve().parent / "data"

# 미국 상장 ETF·지수·뮤추얼펀드(긴 역사용)
US_TICKERS = [
    "SPY", "QQQ", "DIA", "IWM", "EFA", "EEM", "VWO", "VEA", "VT", "URTH", "ACWI",
    "FEZ", "EZU", "VGK", "EWJ", "EWY", "IEF", "TLT", "SHY", "BIL", "SHV", "AGG",
    "BND", "LQD", "HYG", "TIP", "GLD", "IAU", "DBC", "PDBC", "GSG", "VNQ",
    "SSO", "QLD", "UPRO", "TQQQ", "MTUM", "USMV", "FDD", "IWD", "SCZ", "VTI", "SCHD",
    "VFINX", "VUSTX", "VFITX", "VWEHX", "VEURX", "VEIEX", "FSUTX",
    "^GSPC", "^NDX", "^IXIC", "^STOXX50E", "^IRX", "^TNX", "KRW=X", "GC=F",
]

# 국내 상장 ETF (종목코드는 이름으로 다시 확인한다)
KR_TICKERS = [
    "133690.KS",  # TIGER 미국나스닥100
    "360750.KS",  # TIGER 미국S&P500
    "251350.KS",  # KODEX MSCI선진국
    "245350.KS",  # TIGER 유로스탁스배당30
    "411060.KS",  # ACE KRX금현물
    "308620.KS",  # KODEX 미국10년국채선물
    "368590.KS",  # RISE 미국나스닥100
    "379780.KS",  # RISE 미국S&P500
    "418660.KS",  # TIGER 미국나스닥100레버리지(합성)
    "069500.KS",  # KODEX 200
    "102110.KS",  # TIGER 200
    "132030.KS",  # KODEX 골드선물(H)
    "305080.KS",  # TIGER 미국채10년선물
    "153130.KS",  # KODEX 단기채권
    "261240.KS",  # KODEX 미국달러선물
    "304660.KS",  # KODEX 미국채울트라30년선물(H)
    "379800.KS",  # KODEX 미국S&P500TR
    "379810.KS",  # KODEX 미국나스닥100TR
    "195930.KS",  # TIGER 유로스탁스50(합성 H)
    "357870.KS",  # TIGER CD금리투자KIS(합성)
    "423160.KS",  # KODEX KOFR금리액티브(합성)
    "148070.KS",  # KOSEF 국고채10년
    "114260.KS",  # KODEX 국고채3년
    "292150.KS",  # TIGER 코리아TOP10
    "005930.KS",  # 삼성전자
    "000660.KS",  # SK하이닉스
    "005380.KS",  # 현대차
    "024110.KS",  # 기업은행
    # 국내 ETF 호환 후보 (2026-11-09, 이름은 tickers.csv로 확인)
    "195970.KS",  # ARIRANG 선진국MSCI(합성 H)
    "195980.KS",  # ARIRANG 신흥국MSCI(합성 H)
    "446720.KS",  # SOL 미국배당다우존스
    "458730.KS",  # TIGER 미국배당다우존스
    "329750.KS",  # TIGER 미국달러단기채권액티브
    "453850.KS",  # ACE 미국30년국채액티브(H)
    "476760.KS",  # ACE 미국30년국채액티브
    "458250.KS",  # TIGER 미국30년국채스트립액티브(합성 H)
    "280930.KS",  # KODEX 미국러셀2000(H)
    "409820.KS",  # KODEX 미국나스닥100레버리지(합성 H)
    "225040.KS",  # TIGER 미국S&P500레버리지(합성 H)
    "130680.KS",  # TIGER 원유선물Enhanced(H)
    "261220.KS",  # KODEX WTI원유선물(H)
    "271060.KS",  # KODEX 3대농산물선물(H)
    "137610.KS",  # TIGER 농산물선물Enhanced(H)
    "139310.KS",  # TIGER 금속선물(H)
    "319640.KS",  # TIGER 골드선물(H)
    "453870.KS",  # TIGER 미국S&P500동일가중? (확인용)
    "381170.KS",  # TIGER 미국테크TOP10 (확인용)
    "272580.KS",  # TIGER 단기채권액티브
    "455030.KS",  # KODEX 미국달러SOFR금리액티브(합성)
    "189400.KS",  # ARIRANG 글로벌MSCI(합성 H)
    "283580.KS",  # KODEX 차이나CSI300 (확인용)
    "238720.KS",  # KINDEX 일본Nikkei225(H) (확인용)
    "182480.KS",  # TIGER 미국MSCI리츠(합성 H)
    "352560.KS",  # KODEX 미국S&P500선물(H)? (확인용)
    "219480.KS",  # KODEX 미국S&P500선물(H)
    "304940.KS",  # KODEX 미국나스닥100선물(H)
    "448290.KS",  # TIGER 미국S&P500(H)
    "448300.KS",  # TIGER 미국나스닥100(H)
    "472160.KS",  # TIGER 미국테크TOP10 INDXX(H)? (확인용)
    "411420.KS",  # KODEX 미국나스닥100TR? (확인용)
    "429000.KS",  # TIGER 미국S&P500배당귀족 (확인용)
]


def fetch(ticker: str) -> pd.DataFrame | None:
    try:
        df = yf.Ticker(ticker).history(period="max", interval="1d", auto_adjust=False)
    except Exception as exc:  # noqa: BLE001
        print(f"[실패] {ticker}: {exc}")
        return None
    if df is None or df.empty:
        print(f"[없음] {ticker}")
        return None
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df[["Close", "Adj Close", "Volume"]]


def name_of(ticker: str) -> str:
    try:
        info = yf.Ticker(ticker).get_info()
        return info.get("longName") or info.get("shortName") or ""
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    closes, adjs, vols, rows = {}, {}, {}, []
    for t in US_TICKERS + KR_TICKERS:
        df = fetch(t)
        if df is None:
            rows.append({"ticker": t, "name": "", "first": "", "last": "", "rows": 0})
            continue
        closes[t] = df["Close"]
        adjs[t] = df["Adj Close"]
        if t.endswith(".KS"):
            vols[t] = df["Volume"]
        rows.append({
            "ticker": t, "name": name_of(t),
            "first": df.index.min().date(), "last": df.index.max().date(), "rows": len(df),
        })
        print(f"[완료] {t}: {df.index.min().date()} ~ {df.index.max().date()} ({len(df)}행)")
    pd.DataFrame(closes).sort_index().round(6).to_csv(DATA_DIR / "close_daily.csv.gz")
    pd.DataFrame(adjs).sort_index().round(6).to_csv(DATA_DIR / "adjclose_daily.csv.gz")
    # 국내 ETF 거래량(주). 유동성 확인용
    pd.DataFrame(vols).sort_index().to_csv(DATA_DIR / "volume_daily_kr.csv.gz")
    pd.DataFrame(rows).to_csv(DATA_DIR / "tickers.csv", index=False)
    return 0 if closes else 1


if __name__ == "__main__":
    sys.exit(main())
