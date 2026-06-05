# ============================================
# 시그널 엔진 — 단타(스캘핑): 거래량 점화 + VWAP 돌파
# ============================================
"""
전략 핵심(일봉 정배열 → 단타 점화로 전면 교체):
  '정배열 완성'을 기다리면 이미 다 오른 뒤라 늦는다. 그래서 후행 지표 대신
  '지금 거래량이 터지며 가격이 막 치고 올라가는 순간'(ignition)을 잡는다.

평가 봉: 마지막 '확정' 5분봉(형성 중인 미완성 봉은 거래량이 덜 차서 가짜 서지가
  잡히므로 제외). 5분 주기로 돌리면 최대 5~10분 지연 — 일봉 1일 지연과는 차원이 다름.

진입(BUY_IGNITION) — 아래가 동시 충족될 때:
  · RVOL(상대거래량) ≥ 트리거       거래량 폭발 = 지금 수급 유입 (주 트리거)
  · 가격 > VWAP                      당일 매수 우위 (VWAP는 매일 리셋 = 단타 기준선)
  · 직전 N봉 고점 돌파               방향 확인 (거래량만으론 덤핑일 수 있음)
  · EMA9 > EMA21 & EMA9 상승         단기 모멘텀 상방
  · RSI 하한~상한(예 50~72)          모멘텀 충분하되 막차(과매수 80↑)는 차단
  · VWAP 대비 과열도 ≤ 한도          이미 멀리 떠 있으면 추격 금지 ← '늦음' 방지 핵심

청산(EXIT_SCALP) — 보유자 기준, 아래 중 하나:
  · VWAP 하향 이탈(직전 봉 위 → 이번 봉 아래)
  · RSI 과열(≥80) + VWAP 대비 과열   블로우오프, 분할 익절
  · 대량 음봉(RVOL 높음 + 종가<시가) 매도 물량 출회

판정 우선순위: EXIT_SCALP → BUY_IGNITION → WATCH_VOL → HOLD
"""
from datetime import datetime, timezone, timedelta

from core import indicators as ind

KST = timezone(timedelta(hours=9))

LABELS = {
    "BUY_IGNITION": "🟢 매수 점화 (거래량 폭발)",
    "WATCH_VOL": "👀 관찰 (거래량 증가)",
    "HOLD": "⚪ 관망",
    "EXIT_SCALP": "🔴 청산 (이탈/과열)",
}
SCORES = {
    "BUY_IGNITION": 3, "WATCH_VOL": 1, "HOLD": 0, "EXIT_SCALP": -3,
}
BUY_SIDE = {"BUY_IGNITION"}
SELL_SIDE = {"EXIT_SCALP"}
WATCH_LABEL = "WATCH_VOL"


def _kst_date(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, KST).date()


def _kst_hour(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, KST).hour


def estimate_horizon(label, target_pct):
    """예상 보유기간(단타라 전부 초단기). 반환: (분류, 설명) 또는 None."""
    if label == "BUY_IGNITION":
        return ("초단기 스캘핑",
                f"수분~30분 · 목표 +{target_pct * 100:.1f}% 도달 시 분할익절, VWAP 이탈 시 손절")
    return None


def build_playbook(label):
    """진입/보유 후 행동 가이드. 반환: {"hold", "exit"} 또는 None."""
    if label == "BUY_IGNITION":
        return {
            "hold": "거래량(RVOL)이 유지되고 가격이 VWAP 위에 머무는 동안만 짧게 보유",
            "exit": "🔴 VWAP 하향 이탈 / 거래량 소멸 / RSI 80↑ 과열 / 대량 음봉 시 즉시 익절·청산",
        }
    if label == "EXIT_SCALP":
        return {
            "hold": None,
            "exit": "보유 중이면 즉시 청산 — VWAP 이탈 또는 과열·반전(단타는 끌지 않는다)",
        }
    return None


def analyze(candles, cfg):
    """
    candles: bithumb.get_candles() (시간 오름차순). 5분봉 권장.
    반환: dict 또는 None(데이터 부족).
    """
    need = max(cfg.EMA_SLOW, cfg.RVOL_PERIOD + 1,
               cfg.BREAKOUT_LOOKBACK + 1, cfg.RSI_PERIOD + 1) + 3
    if len(candles) < need:
        return None

    # 마지막 봉은 형성 중(미완성)일 수 있어 제외 → 직전 '확정' 봉으로 평가
    ev = candles[:-1]
    if len(ev) < need - 1:
        return None
    cur = ev[-1]

    closes = [c["close"] for c in ev]
    vols = [c["volume"] for c in ev]
    highs = [c["high"] for c in ev]

    price = cur["close"]
    prev_close = closes[-2]
    change_pct = (price - prev_close) / prev_close * 100 if prev_close else 0.0

    # --- RVOL (상대거래량) : 주 트리거 ---
    rvol = ind.volume_surge(vols, cfg.RVOL_PERIOD)
    if rvol is None:
        return None

    # --- VWAP (당일 세션) ---
    today = _kst_date(cur["ts"])
    session = [c for c in ev if _kst_date(c["ts"]) == today]
    vwap = ind.vwap(session)
    prev_vwap = ind.vwap(session[:-1]) if len(session) >= 2 else None
    ext_vwap = (price - vwap) / vwap if vwap else 0.0
    above_vwap = vwap is not None and price > vwap
    prev_above_vwap = (prev_vwap is not None and prev_close > prev_vwap)

    # --- 단기 모멘텀 (EMA9/EMA21) ---
    ef_s = ind.ema_series(closes, cfg.EMA_FAST)
    es_s = ind.ema_series(closes, cfg.EMA_SLOW)
    ef = ef_s[-1] if ef_s else None
    ef_prev = ef_s[-2] if len(ef_s) >= 2 else None
    es = es_s[-1] if es_s else None
    if None in (ef, ef_prev, es):
        return None
    momentum_up = ef > es and ef > ef_prev

    # --- RSI ---
    rsi = ind.rsi(closes, cfg.RSI_PERIOD)
    if rsi is None:
        return None

    # --- 돌파(직전 N봉 고점) ---
    window_highs = highs[-cfg.BREAKOUT_LOOKBACK - 1:-1]  # 현재 봉 제외 직전 N봉
    breakout_high = max(window_highs) if window_highs else None
    breakout = breakout_high is not None and price > breakout_high

    green = price > cur["open"]

    # --- 거래 집중 시간대(예 9시/21시 전후) 가중 ---
    hour = _kst_hour(cur["ts"])
    is_key_hour = hour in cfg.KEY_HOURS
    trigger = max(cfg.RVOL_MIN, cfg.RVOL_TRIGGER - (cfg.KEY_HOUR_RELAX if is_key_hour else 0.0))

    vol_surge = rvol >= trigger
    rsi_ok = cfg.RSI_BUY_MIN <= rsi <= cfg.RSI_BUY_MAX
    not_overheated = ext_vwap <= cfg.MAX_EXT_VWAP

    # --- 청산 조건(보유자 기준) ---
    lost_vwap = (vwap is not None) and (not above_vwap) and prev_above_vwap
    blowoff = rsi >= cfg.RSI_OVERHEAT and ext_vwap >= cfg.MAX_EXT_VWAP
    heavy_dump = (rvol >= trigger) and (not green)

    reasons = []
    if lost_vwap or blowoff or (heavy_dump and above_vwap is False):
        label = "EXIT_SCALP"
        if lost_vwap:
            reasons.append("VWAP 하향 이탈 — 당일 매수 우위 상실")
        if blowoff:
            reasons.append(f"RSI {rsi:.0f} 과열 + VWAP 대비 {ext_vwap * 100:+.1f}% — 블로우오프(분할 익절)")
        if heavy_dump and not above_vwap:
            reasons.append(f"대량 음봉(RVOL {rvol:.1f}배) — 매도 물량 출회")
    elif (vol_surge and above_vwap and breakout and momentum_up
          and rsi_ok and not_overheated and green):
        label = "BUY_IGNITION"
        reasons.append(f"거래량 폭발 RVOL {rvol:.1f}배(트리거 {trigger:.1f})"
                       + (" · 🔥거래 집중 시간대" if is_key_hour else ""))
        reasons.append(f"VWAP 돌파 유지(가격 {ext_vwap * 100:+.1f}%) · 직전 {cfg.BREAKOUT_LOOKBACK}봉 고점 돌파")
        reasons.append(f"EMA{cfg.EMA_FAST}>EMA{cfg.EMA_SLOW} 상승 · RSI {rsi:.0f}")
    elif rvol >= cfg.RVOL_WATCH and above_vwap and ef > es:
        label = "WATCH_VOL"
        reasons.append(f"거래량 증가 RVOL {rvol:.1f}배 · VWAP 위 — 점화 대기"
                       + (" 🔥" if is_key_hour else ""))
        # 왜 아직 진입이 아닌지 한 줄
        miss = []
        if not breakout:
            miss.append("고점 돌파 전")
        if not (cfg.RSI_BUY_MIN <= rsi <= cfg.RSI_BUY_MAX):
            miss.append(f"RSI {rsi:.0f}(밴드 밖)")
        if not not_overheated:
            miss.append(f"VWAP 대비 {ext_vwap * 100:+.1f}% 과열")
        if miss:
            reasons.append("대기 사유: " + ", ".join(miss))
    else:
        label = "HOLD"
        reasons.append("점화 셋업 없음")

    # 매수 시 목표/손절 산정
    target = stop = target_pct = None
    if label == "BUY_IGNITION":
        target = price * (1 + cfg.TARGET_PCT)
        target_pct = cfg.TARGET_PCT
        # 손절: 점화 봉 저점과 VWAP 중 더 가까운(높은) 쪽 — 단타라 타이트하게
        candidates = [cur["low"]]
        if vwap is not None:
            candidates.append(vwap)
        stop = max(candidates)
        if stop >= price:  # 안전장치
            stop = cur["low"]

    horizon = estimate_horizon(label, cfg.TARGET_PCT)
    playbook = build_playbook(label)
    return {
        "label": label,
        "label_kr": LABELS[label],
        "score": SCORES[label],
        "price": price,
        "change_pct": change_pct,
        "rvol": rvol,
        "vwap": vwap,
        "ext_vwap": ext_vwap,
        "rsi": rsi,
        "ema_fast": ef,
        "ema_slow": es,
        "is_key_hour": is_key_hour,
        "target": target,
        "stop": stop,
        "target_pct": target_pct,
        "horizon": horizon,
        "playbook": playbook,
        "reasons": reasons,
        "is_actionable": label in BUY_SIDE or label in SELL_SIDE,
    }
