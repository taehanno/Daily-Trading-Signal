# ============================================
# Bithumb 공개 API 클라이언트 (인증 불필요)
# ============================================
"""
Bithumb Public API
- 티커 전체:   GET https://api.bithumb.com/public/ticker/ALL_{QUOTE}
- 캔들:        GET https://api.bithumb.com/public/candlestick/{SYMBOL}_{QUOTE}/{interval}

캔들 row 포맷: [기준시각(ms), 시가, 종가, 고가, 저가, 거래량]  (모두 문자열)
"""
import time
import requests

BASE = "https://api.bithumb.com/public"
_session = requests.Session()
_session.headers.update({"Accept": "application/json"})


class BithumbError(RuntimeError):
    pass


def _get(url: str, timeout: int = 15) -> dict:
    try:
        r = _session.get(url, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        raise BithumbError(f"요청 실패: {url} ({e})")
    if data.get("status") != "0000":
        raise BithumbError(f"API 오류: {url} → status={data.get('status')}")
    return data["data"]


def get_all_tickers(quote: str = "KRW") -> dict:
    """전체 코인 24H 티커. {symbol: {...}} 반환 ('date' 키 제외)."""
    data = _get(f"{BASE}/ticker/ALL_{quote}")
    data.pop("date", None)
    return data


def top_symbols_by_volume(quote: str = "KRW", top_n: int = 15) -> list:
    """24H 거래대금(acc_trade_value_24H) 기준 상위 심볼 리스트."""
    tickers = get_all_tickers(quote)
    rows = []
    for sym, t in tickers.items():
        try:
            val = float(t.get("acc_trade_value_24H") or t.get("acc_trade_value") or 0)
        except (TypeError, ValueError):
            val = 0.0
        rows.append((sym, val))
    rows.sort(key=lambda x: x[1], reverse=True)
    return [sym for sym, _ in rows[:top_n]]


def get_candles(symbol: str, quote: str = "KRW", interval: str = "1h") -> list:
    """
    캔들 리스트를 시간 오름차순 dict 리스트로 반환.
    각 원소: {ts, open, close, high, low, volume} (float)
    """
    raw = _get(f"{BASE}/candlestick/{symbol}_{quote}/{interval}")
    out = []
    for row in raw:
        try:
            out.append({
                "ts": int(row[0]),
                "open": float(row[1]),
                "close": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4]),
                "volume": float(row[5]),
            })
        except (IndexError, ValueError, TypeError):
            continue
    return out


def polite_sleep(seconds: float):
    """rate-limit 보호용 호출 간 대기."""
    if seconds > 0:
        time.sleep(seconds)
