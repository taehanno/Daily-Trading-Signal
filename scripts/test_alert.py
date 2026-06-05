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


def mk(label, price, chg, rvol, ext_vwap, rsi):
    vwap = price / (1 + ext_vwap) if ext_vwap != -1 else price
    sig = {
        "label": label,
        "label_kr": LABELS[label],
        "score": SCORES[label],
        "price": price,
        "change_pct": chg,
        "rvol": rvol,
        "vwap": vwap,
        "ext_vwap": ext_vwap,
        "rsi": rsi,
        "is_key_hour": True,
        "target": None,
        "stop": None,
        "target_pct": None,
        "horizon": estimate_horizon(label, Config.TARGET_PCT),
        "playbook": build_playbook(label),
        "reasons": ["(합성 테스트 시그널)"],
        "is_actionable": label in BUY_SIDE or label == "EXIT_SCALP",
    }
    if label in BUY_SIDE:
        sig["target"] = price * (1 + Config.TARGET_PCT)
        sig["target_pct"] = Config.TARGET_PCT
        sig["stop"] = vwap
        # 합성 유동성: 호가 0.5% 이내 매도물량 6,000만원 → 권장 최대 3,000만원
        sig["liquidity_krw"] = 60_000_000
        sig["max_buy_krw"] = 30_000_000
        sig["liquidity_slippage"] = Config.LIQUIDITY_SLIPPAGE
        sig["thin_book"] = sig["max_buy_krw"] < Config.THIN_BOOK_KRW
    return sig


def main():
    interval = Config.CANDLE_INTERVAL
    # 1) 단건 알림(진입/청산) — 이벤트 기반 주 경로
    buy = mk("BUY_IGNITION", 95000000, 1.8, 3.4, 0.012, 63)
    sell = mk("EXIT_SCALP", 240000, -2.1, 2.7, -0.005, 58)
    telegram.send(Config, "🧪 <b>단건 알림 테스트(진입)</b>\n"
                  + telegram.build_signal_message("BTC", buy, interval))
    telegram.send(Config, "🧪 <b>단건 알림 테스트(청산)</b>\n"
                  + telegram.build_signal_message("XRP", sell, interval))

    # 2) 현황 다이제스트
    results = [
        ("BTC", buy),
        ("SOL", mk("WATCH_VOL", 320000, 0.9, 2.0, 0.008, 55)),
        ("XRP", sell),
    ]
    since = {"BTC": "2026-06-05 09:00"}
    prev = {"BTC": "WATCH_VOL", "SOL": "HOLD", "XRP": "BUY_IGNITION"}
    msg = telegram.build_status_message(results, since, prev, interval, "[테스트] 합성 시그널")
    ok = telegram.send(Config, "🧪 <b>현황 다이제스트 테스트</b>\n" + msg)
    print("발송 성공" if ok else "발송 실패")


if __name__ == "__main__":
    main()
