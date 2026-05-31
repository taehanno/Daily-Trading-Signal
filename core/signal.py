# ============================================
# 시그널 엔진 — 복합 스코어로 매수/매도 포지션 판정
# ============================================
"""
여러 지표를 점수화해서 합산한 뒤 포지션을 정한다.
점수 > 0 = 매수 우위, < 0 = 매도 우위.

  score >= +4 : STRONG_BUY   (적극 매수)
  +2 ~ +3     : BUY          (매수)
  -1 ~ +1     : HOLD         (관망)
  -2 ~ -3     : SELL         (매도)
  score <= -4 : STRONG_SELL  (적극 매도)

각 판정에는 사람이 읽을 수 있는 근거(reasons)를 함께 담는다.
"""
from core import indicators as ind

LABELS = {
    "STRONG_BUY": "🟢 적극 매수",
    "BUY": "🟢 매수",
    "HOLD": "⚪ 관망",
    "SELL": "🔴 매도",
    "STRONG_SELL": "🔴 적극 매도",
}
BUY_SIDE = {"STRONG_BUY", "BUY"}
SELL_SIDE = {"STRONG_SELL", "SELL"}


def _score_to_label(score):
    if score >= 4:
        return "STRONG_BUY"
    if score >= 2:
        return "BUY"
    if score <= -4:
        return "STRONG_SELL"
    if score <= -2:
        return "SELL"
    return "HOLD"


def analyze(candles, cfg):
    """
    candles: bithumb.get_candles() 결과 (시간 오름차순 dict 리스트)
    cfg: Config
    반환: dict 또는 None(데이터 부족)
    """
    if len(candles) < max(cfg.MA_LONG, cfg.BB_PERIOD, 35) + 1:
        return None

    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]
    price = closes[-1]
    prev_close = closes[-2]
    change_pct = (price - prev_close) / prev_close * 100 if prev_close else 0.0

    score = 0
    reasons = []

    # --- RSI ---
    rsi_val = ind.rsi(closes, cfg.RSI_PERIOD)
    if rsi_val is not None:
        if rsi_val <= cfg.RSI_OVERSOLD:
            score += 2
            reasons.append(f"RSI {rsi_val:.0f} 과매도(↑반등 기대)")
        elif rsi_val <= cfg.RSI_OVERSOLD + 10:
            score += 1
            reasons.append(f"RSI {rsi_val:.0f} 저점권")
        elif rsi_val >= cfg.RSI_OVERBOUGHT:
            score -= 2
            reasons.append(f"RSI {rsi_val:.0f} 과매수(↓조정 위험)")
        elif rsi_val >= cfg.RSI_OVERBOUGHT - 10:
            score -= 1
            reasons.append(f"RSI {rsi_val:.0f} 고점권")

    # --- 이동평균 정배열 / 골든·데드크로스 ---
    ma_s = ind.sma(closes, cfg.MA_SHORT)
    ma_l = ind.sma(closes, cfg.MA_LONG)
    ma_s_prev = ind.sma(closes[:-1], cfg.MA_SHORT)
    ma_l_prev = ind.sma(closes[:-1], cfg.MA_LONG)
    if None not in (ma_s, ma_l, ma_s_prev, ma_l_prev):
        crossed_up = ma_s_prev <= ma_l_prev and ma_s > ma_l
        crossed_dn = ma_s_prev >= ma_l_prev and ma_s < ma_l
        if crossed_up:
            score += 2
            reasons.append(f"골든크로스(MA{cfg.MA_SHORT}>MA{cfg.MA_LONG})")
        elif crossed_dn:
            score -= 2
            reasons.append(f"데드크로스(MA{cfg.MA_SHORT}<MA{cfg.MA_LONG})")
        elif ma_s > ma_l:
            score += 1
            reasons.append("단기 정배열")
        elif ma_s < ma_l:
            score -= 1
            reasons.append("단기 역배열")

    # --- MACD ---
    macd_val = ind.macd(closes)
    if macd_val is not None:
        hist = macd_val["hist"]
        hist_prev = macd_val["hist_prev"]
        if hist_prev is not None and hist_prev <= 0 < hist:
            score += 2
            reasons.append("MACD 상향 교차")
        elif hist_prev is not None and hist_prev >= 0 > hist:
            score -= 2
            reasons.append("MACD 하향 교차")
        elif hist > 0:
            score += 1
        elif hist < 0:
            score -= 1

    # --- 볼린저밴드 ---
    bb = ind.bollinger(closes, cfg.BB_PERIOD, cfg.BB_MULT)
    if bb is not None:
        if bb["pctb"] <= 0.05:
            score += 1
            reasons.append("볼린저 하단 터치(저평가)")
        elif bb["pctb"] >= 0.95:
            score -= 1
            reasons.append("볼린저 상단 터치(과열)")

    # --- 거래량 급증 (방향 강화) ---
    vsurge = ind.volume_surge(volumes, cfg.BB_PERIOD)
    if vsurge is not None and vsurge >= cfg.VOL_SURGE_MULT:
        if change_pct >= 0:
            score += 1
            reasons.append(f"거래량 급증 x{vsurge:.1f}(상승 동반)")
        else:
            score -= 1
            reasons.append(f"거래량 급증 x{vsurge:.1f}(하락 동반)")

    label = _score_to_label(score)
    return {
        "label": label,
        "label_kr": LABELS[label],
        "score": score,
        "price": price,
        "change_pct": change_pct,
        "rsi": rsi_val,
        "macd_hist": macd_val["hist"] if macd_val else None,
        "bb_pctb": bb["pctb"] if bb else None,
        "vol_surge": vsurge,
        "reasons": reasons,
        "is_actionable": label in BUY_SIDE or label in SELL_SIDE,
    }
