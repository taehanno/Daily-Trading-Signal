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
    """최근 거래량 / 직전 period 평균 거래량 비율. 데이터 부족 시 None."""
    if len(volumes) < period + 1:
        return None
    avg = sum(volumes[-period - 1:-1]) / period
    if avg == 0:
        return None
    return volumes[-1] / avg
