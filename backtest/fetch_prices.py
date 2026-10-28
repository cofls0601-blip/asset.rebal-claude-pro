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
    "SSO", "QLD", "UPRO", "TQQQ", "MTUM", "USMV", "FDD", "IWD", "SCZ", "VTI",
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
    return df[["Close", "Adj Close"]]


def name_of(ticker: str) -> str:
    try:
        info = yf.Ticker(ticker).get_info()
        return info.get("longName") or info.get("shortName") or ""
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    closes, adjs, rows = {}, {}, []
    for t in US_TICKERS + KR_TICKERS:
        df = fetch(t)
        if df is None:
            rows.append({"ticker": t, "name": "", "first": "", "last": "", "rows": 0})
            continue
        closes[t] = df["Close"]
        adjs[t] = df["Adj Close"]
        rows.append({
            "ticker": t, "name": name_of(t),
            "first": df.index.min().date(), "last": df.index.max().date(), "rows": len(df),
        })
        print(f"[완료] {t}: {df.index.min().date()} ~ {df.index.max().date()} ({len(df)}행)")
    pd.DataFrame(closes).sort_index().round(6).to_csv(DATA_DIR / "close_daily.csv.gz")
    pd.DataFrame(adjs).sort_index().round(6).to_csv(DATA_DIR / "adjclose_daily.csv.gz")
    pd.DataFrame(rows).to_csv(DATA_DIR / "tickers.csv", index=False)
    return 0 if closes else 1


if __name__ == "__main__":
    sys.exit(main())
