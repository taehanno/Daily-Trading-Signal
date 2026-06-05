# ============================================
# 1. CONFIG — 환경변수 기반 설정
# ============================================
"""
모든 설정은 환경변수로 주입한다. (Render 대시보드 / 로컬 .env)
민감정보(토큰, chat id)는 절대 코드에 하드코딩하지 않는다.
"""
import os


def _get(key: str, default=None):
    val = os.environ.get(key)
    return val if val not in (None, "") else default


def _get_int(key: str, default: int) -> int:
    try:
        return int(_get(key, default))
    except (TypeError, ValueError):
        return default


def _get_float(key: str, default: float) -> float:
    try:
        return float(_get(key, default))
    except (TypeError, ValueError):
        return default


def _get_list(key: str, default=None):
    raw = _get(key)
    if not raw:
        return default or []
    return [x.strip().upper() for x in raw.split(",") if x.strip()]


def _get_int_list(key: str, default=None):
    raw = _get(key)
    if not raw:
        return default or []
    out = []
    for x in raw.split(","):
        x = x.strip()
        if not x:
            continue
        try:
            out.append(int(x))
        except ValueError:
            continue
    return out


class Config:
    # --- 텔레그램 (필수) ---
    TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = _get("TELEGRAM_CHAT_ID")

    # --- 분석 대상 ---
    # COINS 를 지정하면 해당 심볼만, 비우면 24H 거래대금 상위 TOP_N 자동 선정
    COINS = _get_list("COINS", [])
    TOP_N = _get_int("TOP_N", 20)
    # 자동 선정 시 제외할 심볼. 기본은 스테이블코인도 '포함'(빈 리스트).
    EXCLUDE = _get_list("EXCLUDE", [])
    QUOTE = _get("QUOTE", "KRW")              # 마켓 통화
    CANDLE_INTERVAL = _get("CANDLE_INTERVAL", "5m")  # 단타 스캘핑 기본값 (5분봉)

    # --- 스케줄 ---
    CHECK_INTERVAL_MIN = _get_int("CHECK_INTERVAL_MIN", 5)    # 분석 주기(분) — 단타는 5분
    DAILY_SUMMARY_HOUR = _get_int("DAILY_SUMMARY_HOUR", -1)   # 일일 요약 발송 시각(KST, 0~23, -1이면 끔)

    # --- 단타 스캘핑(거래량 점화 + VWAP) 파라미터 ---
    # 단기 모멘텀 EMA (5분봉 기준)
    EMA_FAST = _get_int("EMA_FAST", 9)
    EMA_SLOW = _get_int("EMA_SLOW", 21)
    # RVOL(상대거래량) — 주 트리거
    RVOL_PERIOD = _get_int("RVOL_PERIOD", 20)            # 평균 산정 봉 수
    RVOL_TRIGGER = _get_float("RVOL_TRIGGER", 2.5)       # 진입 거래량 배수
    RVOL_WATCH = _get_float("RVOL_WATCH", 1.8)           # 관찰(점화 대기) 배수
    RVOL_MIN = _get_float("RVOL_MIN", 2.0)              # 시간대 완화해도 이 밑으론 안 내림
    # 돌파/과열 필터
    BREAKOUT_LOOKBACK = _get_int("BREAKOUT_LOOKBACK", 20)  # 직전 N봉 고점 돌파
    MAX_EXT_VWAP = _get_float("MAX_EXT_VWAP", 0.04)        # VWAP 대비 +4% 넘으면 추격 금지(늦음)
    # RSI 밴드 — 모멘텀 충분 + 막차 차단
    RSI_PERIOD = _get_int("RSI_PERIOD", 14)
    RSI_BUY_MIN = _get_float("RSI_BUY_MIN", 50.0)
    RSI_BUY_MAX = _get_float("RSI_BUY_MAX", 72.0)
    RSI_OVERHEAT = _get_float("RSI_OVERHEAT", 80.0)       # 청산(블로우오프) 기준
    # 목표 수익(분할 익절 기준).
    TARGET_PCT = _get_float("TARGET_PCT", 0.025)          # +2.5%
    # 손절 방식: ATR배수>0 이면 ATR, 아니면 STOP_PCT>0 이면 고정%, 둘 다 0이면 봉저점/VWAP
    STOP_PCT = _get_float("STOP_PCT", 0.0)                # 진입가 대비 고정 손절폭(예 0.012=1.2%)
    STOP_ATR_MULT = _get_float("STOP_ATR_MULT", 0.0)      # ATR 배수 손절(예 1.5)
    STOP_ATR_PERIOD = _get_int("STOP_ATR_PERIOD", 14)
    # 거래 집중 시간대(KST 정수 시) — 이 시간대엔 RVOL 트리거 완화
    KEY_HOURS = set(_get_int_list("KEY_HOURS", [8, 9, 10, 20, 21, 22]))
    KEY_HOUR_RELAX = _get_float("KEY_HOUR_RELAX", 0.5)    # 집중 시간대 트리거 인하폭

    # --- 호가창 유동성 기반 '권장 최대 매수금액' ---
    # 매도호가를 이 슬리피지 이내까지 긁었을 때 받쳐주는 KRW = 혼자 호가 안 밀고 살 수 있는 양
    LIQUIDITY_SLIPPAGE = _get_float("LIQUIDITY_SLIPPAGE", 0.005)  # 0.5%
    LIQUIDITY_SAFETY = _get_float("LIQUIDITY_SAFETY", 0.5)       # 그중 권장 비중(절반)
    THIN_BOOK_KRW = _get_float("THIN_BOOK_KRW", 5_000_000)       # 이 밑이면 '호가 얇음' 경고
    # WATCH(점화 대기) 시그널도 알림 보낼지 (기본 off — 노이즈 방지)
    ALERT_ON_WATCH = _get("ALERT_ON_WATCH", "false").lower() == "true"

    # --- 페이퍼 트레이딩(가상매매 자동 기록 — 실시간 포워드 테스트) ---
    # on이면 단건 시그널 알림 대신 가상 진입/청산 + 누적 성적표를 보낸다(실돈 X).
    PAPER_TRADING = _get("PAPER_TRADING", "true").lower() == "true"
    PAPER_FEE = _get_float("PAPER_FEE", 0.001)            # 왕복 수수료 가정(0.1%)
    PAPER_MAX_HOLD_BARS = _get_int("PAPER_MAX_HOLD_BARS", 24)  # 시간손절(봉, 24=2시간)

    # 매수계열(EARLY_BUY/CONFIRMED_BUY) + 매도계열(EARLY_SELL/EXIT)만 알림. HOLD 무시.
    # on_change: 직전 시그널과 달라졌을 때만 알림 (스팸 방지). always: 매 주기 알림.
    ALERT_MODE = _get("ALERT_MODE", "on_change")

    # 매 실행마다 전 종목 '현황' 다이제스트를 무조건 1건 발송할지.
    # true면 변화가 없어도 "직전과 동일"로 표시하고, 각 시그널의 발생 시각을 함께 보여줌.
    # (이 모드에서는 개별 on_change 단건 알림은 끄고 현황 다이제스트로 일원화)
    HOURLY_STATUS = _get("HOURLY_STATUS", "false").lower() == "true"

    # --- 운영 ---
    STATE_FILE = _get("STATE_FILE", "state.json")
    REQUEST_SLEEP = _get_float("REQUEST_SLEEP", 0.15)  # API 호출 간 간격(초, rate-limit 보호)
    DRY_RUN = _get("DRY_RUN", "false").lower() == "true"  # true면 텔레그램 발송 대신 콘솔 출력

    @classmethod
    def validate(cls):
        missing = []
        if not cls.DRY_RUN:
            if not cls.TELEGRAM_BOT_TOKEN:
                missing.append("TELEGRAM_BOT_TOKEN")
            if not cls.TELEGRAM_CHAT_ID:
                missing.append("TELEGRAM_CHAT_ID")
        if missing:
            raise RuntimeError(
                "필수 환경변수 누락: " + ", ".join(missing) +
                " (또는 DRY_RUN=true 로 콘솔 테스트)"
            )
