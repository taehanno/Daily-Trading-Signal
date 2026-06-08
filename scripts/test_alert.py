# ============================================
# 알림 렌더링 + 실제 텔레그램 발송 테스트 (합성 시그널)
# ============================================
"""
실시간 종목이 전부 관망이면 새 매수/청산 블록을 볼 수 없으므로,
합성(가짜) 단타 시그널로 단건 알림 + 현황 다이제스트를 만들어 텔레그램으로 보낸다.

실행:
  # 실제 발송 (배포에 넣어둔 값과 동일하게 환경변수 주입)
  TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python scripts/test_alert.py

  # 발송 없이 콘솔만 (자격증명 불필요)
  DRY_RUN=true python scripts/test_alert.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from config import Config
from core.signal import build_playbook, estimate_horizon, LABELS, SCORES, BUY_SIDE
from notifier import telegram


def mk(label, price, chg, rvol):
    sig = {
        "label": label,
        "label_kr": LABELS[label],
        "score": SCORES[label],
        "price": price,
        "change_pct": chg,
        "rvol": rvol,
        "atr": price * 0.03,
        "breakout_high": price * 0.99,
        "don_n": Config.SWING_DON_N,
        "don_exit": Config.SWING_DON_EXIT,
        "exit_level": price * 0.95,
        "stop": None,
        "target": None,
        "target_pct": None,
        "ema_fast": price * 0.98,
        "ema_slow": price * 0.95,
        "hold_text": "2~4주",
        "horizon": estimate_horizon(label),
        "playbook": build_playbook(label),
        "reasons": ["(합성 테스트 시그널)"],
        "is_actionable": label in BUY_SIDE or label == "EXIT_SCALP",
    }
    if label in BUY_SIDE:
        sig["stop"] = price * 0.92          # ATR 손절(합성)
        # 합성 유동성: 호가 0.5% 이내 매도물량 6,000만원 → 권장 최대 3,000만원
        sig["liquidity_krw"] = 60_000_000
        sig["max_buy_krw"] = 30_000_000
        sig["liquidity_slippage"] = Config.LIQUIDITY_SLIPPAGE
        sig["thin_book"] = sig["max_buy_krw"] < Config.THIN_BOOK_KRW
    return sig


def main():
    interval = Config.CANDLE_INTERVAL
    # 1) 단건 알림(진입/청산) — 이벤트 기반 주 경로
    buy = mk("BUY_IGNITION", 95000000, 4.8, 3.4)
    sell = mk("EXIT_SCALP", 240000, -6.1, 1.2)
    telegram.send(Config, "🧪 <b>단건 알림 테스트(진입)</b>\n"
                  + telegram.build_signal_message("BTC", buy, interval))
    telegram.send(Config, "🧪 <b>단건 알림 테스트(청산)</b>\n"
                  + telegram.build_signal_message("XRP", sell, interval))

    # 2) 현황 다이제스트
    results = [
        ("BTC", buy),
        ("SOL", mk("WATCH_VOL", 320000, 0.9, 1.4)),
        ("XRP", sell),
    ]
    since = {"BTC": "2026-06-05 09:00"}
    prev = {"BTC": "WATCH_VOL", "SOL": "HOLD", "XRP": "BUY_IGNITION"}
    msg = telegram.build_status_message(results, since, prev, interval, "[테스트] 합성 시그널")
    telegram.send(Config, "🧪 <b>현황 다이제스트 테스트</b>\n" + msg)

    # 3) 페이퍼 진입/청산/일일요약
    entry_ev = {"type": "entry", "sym": "BTC", "sig": buy}
    telegram.send(Config, "🧪 <b>페이퍼 진입 테스트</b>\n"
                  + telegram.build_paper_entry(entry_ev, interval))
    exit_ev = {
        "sym": "BTC", "net": 0.342, "reason": "engine_exit", "entry": 95000000,
        "exit": 127490000, "in": "2026-05-20 09:00", "out": "2026-06-07 09:00",
        "days": 18, "exit_level": 124000000,
        "scorecard": {"n": 12, "wr": 33.3, "exp": 4.1, "pf": 2.8, "total": 49.2},
    }
    telegram.send(Config, "🧪 <b>페이퍼 청산 테스트</b>\n" + telegram.build_paper_exit(exit_ev))
    pap = {
        "open": {"XLM": {"entry": 320000, "entry_ts": "2026-06-05 09:00", "max_buy_krw": 320_000_000}},
        "stats": {"n": 12, "wins": 4, "sum": 0.492, "gp": 0.62, "gl": 0.128},
        "recent": [{"sym": "BTC", "net": 0.342, "reason": "engine_exit", "out": "2026-06-07 09:00"},
                   {"sym": "ENA", "net": -0.061, "reason": "stop", "out": "2026-06-02 09:00"}],
    }
    ok = telegram.send(Config, "🧪 <b>페이퍼 일일요약 테스트</b>\n"
                       + telegram.build_paper_summary(pap, "2026-06-05 09:00", interval))
    print("발송 성공" if ok else "발송 실패")


if __name__ == "__main__":
    main()
