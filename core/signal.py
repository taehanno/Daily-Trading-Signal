# ============================================
# 시그널 엔진 — 일봉 EMA(5/20/60) 정배열 단계 + 선제(낌세) 판정
# ============================================
"""
전략 핵심: 가격이 EMA60 아래에서 바닥을 다지다가 EMA5 위로 올라오며
정배열(EMA5>EMA20>EMA60)로 가려는 '낌세'를 선제적으로 포착한다.
완전 정배열이 완성된 뒤 매수하면 늦으므로, '정배열 직전' 단계를 핵심 매수 시그널로 본다.

판정 우선순위(먼저 맞는 것 채택):
  EXIT          EMA60>EMA20>EMA5 역배열 '전환'        → 적극 매도(청산)
  EARLY_SELL    EMA20>EMA5>EMA60                      → 매도(1차 익절)  ※사용자 규칙
  CONFIRMED_BUY EMA5>EMA20>EMA60 정배열 '방금' 완성    → 매수(늦음, 짧게)
  EARLY_BUY     EMA5>EMA20 & EMA20<=EMA60 & 바닥 출신  → 선제 매수 ⭐핵심
  WATCH         바닥권에서 EMA5 회복(전조)             → 관찰(기본 알림 off)
  HOLD          그 외                                  → 관망
"""
from core import indicators as ind

LABELS = {
    "EARLY_BUY": "🟢 선제 매수 (정배열 임박)",
    "CONFIRMED_BUY": "🟢 매수 (정배열 확정)",
    "WATCH": "👀 관찰 (바닥 다지기)",
    "HOLD": "⚪ 관망",
    "EARLY_SELL": "🔴 매도 (단기선 이탈)",
    "EXIT": "🔴 적극 매도 (추세 종료)",
}
SCORES = {
    "EARLY_BUY": 3, "CONFIRMED_BUY": 2, "WATCH": 1,
    "HOLD": 0, "EARLY_SELL": -2, "EXIT": -3,
}
BUY_SIDE = {"EARLY_BUY", "CONFIRMED_BUY"}
SELL_SIDE = {"EARLY_SELL", "EXIT"}


def _tail(series, n=0):
    """series 끝에서 n번째 값(0=마지막). 부족하면 None."""
    if not series or len(series) <= n:
        return None
    return series[-1 - n]


def estimate_horizon(label, ext):
    """
    예상 보유기간 추정. ext = (price - EMA5) / EMA5 (EMA5 대비 과열도).
    반환: (분류, 설명) 또는 None.
    ※ 추정치이며 실제 청산 기준은 매도 시그널(EARLY_SELL/EXIT).
    """
    if label == "EARLY_BUY":
        # 이미 단기 급등(EMA5 대비 과열)이면 추격 자제 — 눌림목 대기
        if ext > 0.20:
            return ("스윙(과열주의)", "급등 상태 · 추격 자제, 눌림목(EMA5 회귀) 대기 권장")
        # 바닥에서 막 올라오는 단계 → 추세 초입, 며칠 묵어두기 적합
        return ("스윙·중기", "1~4주 (7~30일) · 며칠 묵어두기 적합 · 1차 점검 D+3")
    if label == "CONFIRMED_BUY":
        # 이미 정배열 완성 = 늦은 진입. 과열도가 클수록 빨리 빠져야 함
        if ext > 0.30:
            return ("초단기", "1~2시간 · 극과열, 즉시 분할 익절")
        if ext > 0.20:
            return ("초단기", "2~4시간 · 과열")
        if ext > 0.13:
            return ("단기", "4~12시간")
        if ext > 0.08:
            return ("단기", "12~24시간")
        return ("단기", "1~3일 · 늦은 진입, 짧게")
    return None


def analyze(candles, cfg):
    """
    candles: bithumb.get_candles() (시간 오름차순). 일봉 권장.
    반환: dict 또는 None(데이터 부족).
    """
    closes = [c["close"] for c in candles]
    need = cfg.EMA_SLOW + cfg.SLOPE_LOOKBACK + 2
    if len(closes) < need:
        return None

    e5s = ind.ema_series(closes, cfg.EMA_FAST)
    e20s = ind.ema_series(closes, cfg.EMA_MID)
    e60s = ind.ema_series(closes, cfg.EMA_SLOW)
    e5, e20, e60 = _tail(e5s), _tail(e20s), _tail(e60s)
    e5p, e20p, e60p = _tail(e5s, 1), _tail(e20s, 1), _tail(e60s, 1)
    lb = cfg.SLOPE_LOOKBACK
    e5b, e20b, e60b = _tail(e5s, lb), _tail(e20s, lb), _tail(e60s, lb)
    if None in (e5, e20, e60, e5p, e20p, e60p, e5b, e20b, e60b):
        return None

    price = closes[-1]
    prev = closes[-2]
    change_pct = (price - prev) / prev * 100 if prev else 0.0
    # EMA 기울기(%) — 추세 방향/강도
    s5 = (e5 - e5b) / e5b * 100 if e5b else 0.0
    s20 = (e20 - e20b) / e20b * 100 if e20b else 0.0
    s60 = (e60 - e60b) / e60b * 100 if e60b else 0.0
    ext = (price - e5) / e5 if e5 else 0.0

    # 바닥 다지기: 최근 BASE_WINDOW 일 종가가 EMA60 아래였던 비율
    w = closes[-cfg.BASE_WINDOW:]
    base_below = sum(1 for c in w if c < e60) / len(w)
    base_ok = base_below >= cfg.BASE_BELOW_RATIO

    # 정렬 상태
    bull_full = e5 > e20 > e60
    bull_full_prev = e5p > e20p > e60p
    bear_full = e60 > e20 > e5
    bear_full_prev = e60p > e20p > e5p
    early_sell = e20 > e5 > e60          # 사용자 매도 규칙
    pre_bull = (e5 > e20) and (e20 <= e60)  # 정배열 직전

    reasons = []
    if bear_full and not bear_full_prev:
        label = "EXIT"
        reasons.append("EMA60>20>5 역배열 전환 · 추세 종료")
    elif early_sell:
        label = "EARLY_SELL"
        reasons.append("EMA20>EMA5>EMA60 · 단기선 이탈(1차 익절)")
    elif bull_full and not bull_full_prev:
        label = "CONFIRMED_BUY"
        reasons.append("EMA5>20>60 정배열 완성(확정)")
    elif pre_bull and price > e5 and s5 > 0 and base_ok:
        label = "EARLY_BUY"
        reasons.append("정배열 직전: EMA5>EMA20, EMA60 아직 위 · 바닥 다진 뒤 EMA5 상향")
    elif base_ok and price > e5 and s5 > 0 and e5 < e20:
        label = "WATCH"
        reasons.append("바닥권에서 가격이 EMA5 회복 · 정배열 전조 관찰")
    elif bull_full:
        label = "HOLD"
        reasons.append("정배열 유지 중(보유 구간)")
    else:
        label = "HOLD"
        reasons.append("뚜렷한 셋업 없음")

    # 보조 근거
    reasons.append(f"EMA5 기울기 {s5:+.1f}% · EMA20 {s20:+.1f}% · EMA60 {s60:+.1f}%")
    if label in BUY_SIDE:
        reasons.append(f"EMA5 대비 가격 {ext * 100:+.1f}% (과열도)")
    if base_ok and label in BUY_SIDE | {"WATCH"}:
        reasons.append(f"최근 {cfg.BASE_WINDOW}봉 중 {base_below * 100:.0f}% EMA60 아래(바닥)")

    horizon = estimate_horizon(label, ext)
    return {
        "label": label,
        "label_kr": LABELS[label],
        "score": SCORES[label],
        "price": price,
        "change_pct": change_pct,
        "ema_fast": e5,
        "ema_mid": e20,
        "ema_slow": e60,
        "ext": ext,
        "slope_fast": s5,
        "base_below": base_below,
        "horizon": horizon,           # (분류, 설명) or None
        "reasons": reasons,
        "is_actionable": label in BUY_SIDE or label in SELL_SIDE,
    }
