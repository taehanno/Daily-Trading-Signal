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
    CANDLE_INTERVAL = _get("CANDLE_INTERVAL", "24h")  # 일봉 전략 기본값 (24h)

    # --- 스케줄 ---
    CHECK_INTERVAL_MIN = _get_int("CHECK_INTERVAL_MIN", 60)   # 분석 주기(분)
    DAILY_SUMMARY_HOUR = _get_int("DAILY_SUMMARY_HOUR", 9)    # 일일 요약 발송 시각(KST, 0~23, -1이면 끔)

    # --- EMA 정배열 단계 시그널 파라미터 ---
    EMA_FAST = _get_int("EMA_FAST", 5)
    EMA_MID = _get_int("EMA_MID", 20)
    EMA_SLOW = _get_int("EMA_SLOW", 60)
    SLOPE_LOOKBACK = _get_int("SLOPE_LOOKBACK", 3)   # EMA 기울기 측정 봉 수
    BASE_WINDOW = _get_int("BASE_WINDOW", 12)        # 바닥 다지기 판정 구간(봉)
    BASE_BELOW_RATIO = _get_float("BASE_BELOW_RATIO", 0.5)  # 구간 중 EMA60 아래 비율
    # 참고용 보조지표
    RSI_PERIOD = _get_int("RSI_PERIOD", 14)
    # WATCH(전조) 시그널도 알림 보낼지 (기본 off — 노이즈 방지)
    ALERT_ON_WATCH = _get("ALERT_ON_WATCH", "false").lower() == "true"

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
