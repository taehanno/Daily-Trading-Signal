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
    TOP_N = _get_int("TOP_N", 15)
    # 자동 선정 시 제외할 심볼 (스테이블코인 등 — KRW 환율 노이즈라 시그널 무의미)
    EXCLUDE = _get_list("EXCLUDE", ["USDT", "USDC", "DAI", "BUSD", "TUSD", "FDUSD", "PYUSD"])
    QUOTE = _get("QUOTE", "KRW")              # 마켓 통화
    CANDLE_INTERVAL = _get("CANDLE_INTERVAL", "1h")  # 1m,3m,5m,10m,30m,1h,6h,12h,24h

    # --- 스케줄 ---
    CHECK_INTERVAL_MIN = _get_int("CHECK_INTERVAL_MIN", 60)   # 분석 주기(분)
    DAILY_SUMMARY_HOUR = _get_int("DAILY_SUMMARY_HOUR", 9)    # 일일 요약 발송 시각(KST, 0~23, -1이면 끔)

    # --- 시그널 임계값 ---
    RSI_PERIOD = _get_int("RSI_PERIOD", 14)
    RSI_OVERSOLD = _get_float("RSI_OVERSOLD", 30)
    RSI_OVERBOUGHT = _get_float("RSI_OVERBOUGHT", 70)
    MA_SHORT = _get_int("MA_SHORT", 7)
    MA_LONG = _get_int("MA_LONG", 25)
    BB_PERIOD = _get_int("BB_PERIOD", 20)
    BB_MULT = _get_float("BB_MULT", 2.0)
    VOL_SURGE_MULT = _get_float("VOL_SURGE_MULT", 1.8)  # 평균 대비 거래량 급증 배수

    # 알림을 보낼 최소 시그널 강도: STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL
    # "BUY" 이상(매수계열) + "SELL" 이하(매도계열)만 알림. HOLD 는 무시.
    ALERT_ON_HOLD = _get("ALERT_ON_HOLD", "false").lower() == "true"
    # on_change: 직전 시그널과 달라졌을 때만 알림 (스팸 방지). always: 매 주기 알림.
    ALERT_MODE = _get("ALERT_MODE", "on_change")

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
