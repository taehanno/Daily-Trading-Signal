# ============================================
# 기술적 지표 (순수 파이썬, 외부 의존성 없음)
# ============================================
"""
입력은 종가/거래량 리스트(시간 오름차순). 데이터 부족 시 None 또는 빈 결과 반환.
"""


def sma(values, period):
    """단순이동평균. 마지막 period개 평균."""
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(values, period):
    """EMA 시계열 전체 반환. 첫 값은 초기 SMA로 시작."""
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    seed = sum(values[:period]) / period
    out = [seed]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes, period=14):
    """Wilder RSI. 0~100. 데이터 부족 시 None."""
    if len(closes) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    # 이후 구간 Wilder 평활
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = diff if diff > 0 else 0.0
        loss = -diff if diff < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(closes, fast=12, slow=26, signal=9):
    """
    MACD. 반환: {'macd', 'signal', 'hist'} (마지막 값). 데이터 부족 시 None.
    """
    if len(closes) < slow + signal:
        return None
    ema_fast = ema_series(closes, fast)
    ema_slow = ema_series(closes, slow)
    # 두 EMA 시계열 길이 정렬 (slow가 더 짧게 시작)
    offset = len(ema_fast) - len(ema_slow)
    macd_line = [ema_fast[i + offset] - ema_slow[i] for i in range(len(ema_slow))]
    signal_line = ema_series(macd_line, signal)
    if not signal_line:
        return None
    macd_val = macd_line[-1]
    signal_val = signal_line[-1]
    return {
        "macd": macd_val,
        "signal": signal_val,
        "hist": macd_val - signal_val,
        # 직전 히스토그램(교차 감지용)
        "hist_prev": (macd_line[-2] - signal_line[-2]) if len(signal_line) >= 2 else None,
    }


def bollinger(closes, period=20, mult=2.0):
    """볼린저밴드. 반환: {'mid','upper','lower','pctb'}. 데이터 부족 시 None."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    mid = sum(window) / period
    var = sum((x - mid) ** 2 for x in window) / period
    std = var ** 0.5
    upper = mid + mult * std
    lower = mid - mult * std
    price = closes[-1]
    # %B: 0이면 하단, 1이면 상단
    pctb = (price - lower) / (upper - lower) if upper != lower else 0.5
    return {"mid": mid, "upper": upper, "lower": lower, "pctb": pctb}


def volume_surge(volumes, period=20):
    """최근 거래량 / 직전 period 평균 거래량 비율(RVOL). 데이터 부족 시 None."""
    if len(volumes) < period + 1:
        return None
    avg = sum(volumes[-period - 1:-1]) / period
    if avg == 0:
        return None
    return volumes[-1] / avg


def median_turnover(candles, days=30):
    """최근 days봉의 대표 거래대금(close×volume, KRW)의 중앙값.
    펌프성 잡코인(평소 거의 안 거래되다 가끔 거래량만 터져 거래대금 상위에 잠깐 끼는)을
    걸러내는 유니버스 품질 지표. 검증(scripts/backtest_swing.py per-symbol): 백테스트
    PF<1 패자(G·MANTA)는 중앙값 ~0.5억, 흑자 메이저는 20억~900억으로 명확히 갈림.
    데이터 없으면 0."""
    rows = candles[-days:] if candles else []
    tos = sorted(c["close"] * c["volume"] for c in rows)
    if not tos:
        return 0.0
    m = len(tos) // 2
    return tos[m] if len(tos) % 2 else (tos[m - 1] + tos[m]) / 2


def vwap(candles):
    """
    거래량가중평균가(VWAP). candles: [{high, low, close, volume}, ...].
    당일 단타 기준선 — 보통 '오늘 세션' 캔들만 넘긴다(호출 측에서 슬라이스).
    각 봉의 대표가(high+low+close)/3 를 거래량으로 가중평균. 데이터 부족/거래량 0 시 None.
    """
    num = 0.0
    den = 0.0
    for c in candles:
        typ = (c["high"] + c["low"] + c["close"]) / 3.0
        num += typ * c["volume"]
        den += c["volume"]
    return num / den if den > 0 else None


def atr(candles, period=14):
    """
    Average True Range(변동성). candles: [{high, low, close}, ...] 오름차순.
    손절폭 산정용. 데이터 부족 시 None.
    """
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h, l = candles[i]["high"], candles[i]["low"]
        pc = candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    # Wilder 평활
    atr_val = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr_val = (atr_val * (period - 1) + tr) / period
    return atr_val
