# ============================================
# 알림 렌더링 + 실제 텔레그램 발송 테스트 (합성 시그널)
# ============================================
"""
현재 실시간 종목이 전부 관망이면 새 매수/매도 블록을 볼 수 없으므로,
합성(가짜) 시그널로 매시간 현황 다이제스트를 만들어 실제 텔레그램으로 보낸다.

실행:
  # 실제 발송 (Render에 넣어둔 값과 동일하게 환경변수 주입)
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
from core.signal import build_playbook, estimate_horizon, LABELS
from notifier import telegram


def mk(label, ext, chg):
    return {
        "label": label,
        "label_kr": LABELS[label],
        "change_pct": chg,
        "horizon": estimate_horizon(label, ext),
        "playbook": build_playbook(label, ext),
    }


def main():
    results = [
        ("BTC", mk("EARLY_BUY", 0.05, 2.3)),
        ("SOL", mk("CONFIRMED_BUY", 0.25, 8.1)),
        ("XRP", mk("EARLY_SELL", 0.0, -3.2)),
        ("DOGE", mk("EXIT", 0.0, -6.0)),
    ]
    since = {"BTC": "2026-05-30 09:00"}
    prev = {"BTC": "EARLY_BUY", "SOL": "WATCH", "XRP": "CONFIRMED_BUY", "DOGE": "EARLY_SELL"}
    msg = telegram.build_status_message(results, since, prev, "24h", "[테스트] 합성 시그널")
    ok = telegram.send(Config, "🧪 <b>알림 테스트</b>\n" + msg)
    print("발송 성공" if ok else "발송 실패")


if __name__ == "__main__":
    main()
