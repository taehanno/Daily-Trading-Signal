# ============================================
# 시그널 엔진 — 일봉 스윙: 돈치안 돌파 + 거래량 급증
# ============================================
"""
전략(단타 전면 폐기 → 일봉 스윙 추세추종):
  5분·1시간 단타는 수수료에 엣지가 먹혀 전부 본전~마이너스로 검증됨. 시간축을 일봉으로
  올리면 한 번의 추세를 며칠~몇주 먹으므로 수수료가 무의미해지고, 추세추종 본연의 엣지
  (손실 짧게·수익 길게 = 양의 왜도)가 살아난다. (검증: scripts/backtest_swing.py,
  ~1050일 train/test 양쪽 PF 3.4~4.0 out-of-sample)

평가 봉: 마지막 '확정' 봉(형성 중인 봉 제외). 같은 확정봉을 여러 번 돌려도
  on_change/페이퍼 멱등 처리로 중복 없음.

봉 간격은 CANDLE_INTERVAL 로 파라미터화 — 파라미터는 전부 '봉 수' 단위라 12h 운용 시
  돈치안 20봉=10일 채널이 되어 더 짧은 스윙이 된다. (검증: SWING_INTERVAL=12h 백테스트,
  RVOL≥1.5 에서 940일 322건·train/test PF 2.0/2.1 — 일봉 대비 신호 1.7배·건당 엣지는 낮음)
  사용자 문구는 bars_days_txt()로 실제 일수로 환산해 표시한다.

진입(BUY_IGNITION = 스윙 매수) — 동시 충족:
  · 종가 > 직전 SWING_DON_N일 고점 (돈치안 돌파 = 신고가 추세 점화)
  · 거래량(RVOL) ≥ SWING_RVOL_MIN   지금 수급/뉴스 유입(돌파의 진위 확인)  ← 핵심 선별
  · EMA_FAST > EMA_SLOW             상위 추세 상방
  손절 = 진입가 - SWING_ATR_STOP × ATR
  청산선 = 직전 SWING_DON_EXIT일 저점 (이 아래로 일봉 종가 마감 시 매도)
  목표 = 없음(고정 목표는 엣지를 죽임 — 추세 유지되는 한 보유)

청산(EXIT_SCALP = 추세 전환) — 보유자 기준:
  · 종가 < 직전 SWING_DON_EXIT일 저점 (채널 이탈 = 추세 꺾임)
  (손절·시간손절은 페이퍼/백테스트 정산기가 처리)

판정 우선순위: EXIT_SCALP → BUY_IGNITION → WATCH_VOL → HOLD
"""
from datetime import datetime, timezone, timedelta

from core import indicators as ind

KST = timezone(timedelta(hours=9))

LABELS = {
    "BUY_IGNITION": "📈 스윙 매수 (돌파+거래량)",
    "WATCH_VOL": "👀 관찰 (돌파 임박)",
    "HOLD": "⚪ 관망",
    "EXIT_SCALP": "🔴 청산 (추세 전환)",
}
SCORES = {
    "BUY_IGNITION": 3, "WATCH_VOL": 1, "HOLD": 0, "EXIT_SCALP": -3,
}
BUY_SIDE = {"BUY_IGNITION"}
SELL_SIDE = {"EXIT_SCALP"}
WATCH_LABEL = "WATCH_VOL"

HOLD_TEXT = "2~4주"   # 일봉 돈치안20 기준 기본값 — analyze()가 봉 간격에 맞춰 갱신


def _bar_hours(interval):
    """봉 간격 문자열('24h','12h','30m'…) → 시간 수. 해석 불가면 24(일봉 취급)."""
    try:
        if interval.endswith("m"):
            return int(interval[:-1]) / 60
        if interval.endswith("h"):
            return int(interval[:-1])
    except (ValueError, AttributeError):
        pass
    return 24


def bars_days_txt(bars, interval):
    """봉 수 → 실제 일수 표기(12h봉 20개 → '10일'). 봉≠일 오해 방지용 표시 전용."""
    d = bars * _bar_hours(interval) / 24
    return f"{d:g}일"


def bar_word(interval):
    """청산 판정 기준 봉 명칭 — 일봉이 아니면 간격을 명시해 종가 마감 시점 오해 방지."""
    return "일봉" if _bar_hours(interval) >= 24 else f"{interval}봉"


def _hold_text(don_days):
    """진입 채널 길이(일)에 비례한 예상 보유기간 문구."""
    if don_days >= 20:
        return "2~4주"
    if don_days >= 10:
        return "1~2주"
    if don_days >= 5:
        return "3~10일"
    return "수일"


def estimate_horizon(label, hold_text=HOLD_TEXT, exit_txt="10일"):
    """예상 보유기간. 반환: (분류, 설명) 또는 None."""
    if label == "BUY_IGNITION":
        return ("스윙 추세추종",
                f"보통 {hold_text} 보유 · 추세 유지되는 한 보유, {exit_txt} 저점(청산선) 이탈 시 매도")
    return None


def build_playbook(label, exit_txt="10일", bar_txt="일봉"):
    """진입/보유 후 행동 가이드. 반환: {"hold", "exit"} 또는 None."""
    if label == "BUY_IGNITION":
        return {
            "hold": f"{bar_txt} 종가가 청산선({exit_txt} 저점) 위에 머무는 동안 보유 — 추세 살아있음",
            "exit": f"🔴 {bar_txt} 종가가 청산선({exit_txt} 저점) 아래 마감 / ATR 손절가 도달 시 매도",
        }
    if label == "EXIT_SCALP":
        return {
            "hold": None,
            "exit": f"보유 중이면 매도 — {exit_txt} 저점 종가 이탈로 추세 꺾임(스윙은 추세 끝나면 정리)",
        }
    return None


def analyze(candles, cfg):
    """
    candles: bithumb.get_candles() (시간 오름차순). 일봉 권장.
    반환: dict 또는 None(데이터 부족).
    """
    need = max(cfg.SWING_DON_N + 1, cfg.SWING_DON_EXIT + 1,
               cfg.SWING_ATR_PERIOD + 1, cfg.SWING_RVOL_PERIOD + 1,
               cfg.SWING_EMA_SLOW) + 3
    if len(candles) < need:
        return None

    # 마지막 봉은 형성 중(미완성) → 직전 '확정' 일봉으로 평가
    ev = candles[:-1]
    if len(ev) < need - 1:
        return None
    cur = ev[-1]

    closes = [c["close"] for c in ev]
    highs = [c["high"] for c in ev]
    lows = [c["low"] for c in ev]
    vols = [c["volume"] for c in ev]

    price = cur["close"]
    prev_close = closes[-2]
    change_pct = (price - prev_close) / prev_close * 100 if prev_close else 0.0

    # --- RVOL (현재 거래량 / 직전 평균) : 돌파의 진위 + 현재 수급/뉴스 ---
    rvol = ind.volume_surge(vols, cfg.SWING_RVOL_PERIOD)
    if rvol is None:
        return None

    # --- 추세(EMA) ---
    ef_s = ind.ema_series(closes, cfg.SWING_EMA_FAST)
    es_s = ind.ema_series(closes, cfg.SWING_EMA_SLOW)
    ef = ef_s[-1] if ef_s else None
    es = es_s[-1] if es_s else None
    if None in (ef, es):
        return None
    uptrend = ef > es

    # --- ATR (손절폭) ---
    atr = ind.atr(ev, cfg.SWING_ATR_PERIOD)

    # --- 돈치안 채널(현재 봉 제외 직전 N일) ---
    breakout_high = max(highs[-cfg.SWING_DON_N - 1:-1])
    exit_level = min(lows[-cfg.SWING_DON_EXIT - 1:-1])

    breakout = price > breakout_high
    vol_surge = rvol >= cfg.SWING_RVOL_MIN
    channel_break = price < exit_level

    # 표시용: 봉 수를 실제 일수로 환산(12h봉 20개 = '10일' 채널)
    don_txt = bars_days_txt(cfg.SWING_DON_N, cfg.CANDLE_INTERVAL)
    exit_txt = bars_days_txt(cfg.SWING_DON_EXIT, cfg.CANDLE_INTERVAL)
    bar_txt = bar_word(cfg.CANDLE_INTERVAL)
    hold_text = _hold_text(cfg.SWING_DON_N * _bar_hours(cfg.CANDLE_INTERVAL) / 24)

    reasons = []
    if channel_break:
        label = "EXIT_SCALP"
        reasons.append(f"{bar_txt} 종가가 {exit_txt} 저점({exit_level:,.4f}) 아래 — 추세 전환, 매도")
    elif breakout and vol_surge and uptrend:
        label = "BUY_IGNITION"
        reasons.append(f"{don_txt} 고점 돌파(신고가) · 거래량 {rvol:.1f}배 급증 — 지금 수급/뉴스 유입")
        reasons.append(f"EMA{cfg.SWING_EMA_FAST}>EMA{cfg.SWING_EMA_SLOW} 상승추세")
    elif breakout and uptrend and not vol_surge:
        label = "WATCH_VOL"
        reasons.append(f"{don_txt} 고점 돌파했으나 거래량 {rvol:.1f}배(<{cfg.SWING_RVOL_MIN:.1f}) — 거래량 확인 대기")
    elif uptrend and price >= breakout_high * 0.97:
        label = "WATCH_VOL"
        reasons.append(f"{don_txt} 고점({breakout_high:,.4f}) 근접 · 돌파 임박")
    else:
        label = "HOLD"
        reasons.append("돌파 셋업 없음")

    # 매수 시 손절/청산선 산정
    stop = None
    if label == "BUY_IGNITION":
        stop = price - cfg.SWING_ATR_STOP * atr if atr else exit_level
        if stop >= price:  # 안전장치
            stop = exit_level

    horizon = estimate_horizon(label, hold_text, exit_txt)
    playbook = build_playbook(label, exit_txt, bar_txt)
    return {
        "label": label,
        "label_kr": LABELS[label],
        "score": SCORES[label],
        "price": price,
        "change_pct": change_pct,
        "rvol": rvol,
        "atr": atr,
        "breakout_high": breakout_high,
        "don_n": cfg.SWING_DON_N,
        "don_exit": cfg.SWING_DON_EXIT,
        "don_n_txt": don_txt,              # 표시용 실제 일수(봉 간격 환산)
        "don_exit_txt": exit_txt,
        "bar_txt": bar_txt,
        "exit_level": exit_level,          # 청산선(N일 저점) = '팔아야 하는 가격'(갱신됨)
        "stop": stop,                      # ATR 손절가
        "target": None,                    # 스윙은 고정 목표 없음(추세 끝까지)
        "target_pct": None,
        "ema_fast": ef,
        "ema_slow": es,
        "hold_text": hold_text,
        "horizon": horizon,
        "playbook": playbook,
        "reasons": reasons,
        "is_actionable": label in BUY_SIDE or label in SELL_SIDE,
    }
