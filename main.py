# ============================================
# 메인 오케스트레이터 — 분석 루프 + 스케줄
# ============================================
"""
실행:  python main.py
- CHECK_INTERVAL_MIN 마다 대상 코인을 분석
- on_change 모드: 직전 시그널과 달라진 actionable 시그널만 즉시 알림
- DAILY_SUMMARY_HOUR(KST)에 하루 한 번 전체 요약 발송
"""
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta

# Windows 콘솔(cp949)에서 한글/특수문자 출력 깨짐 방지
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from config import Config
from exchanges import bithumb
from core import signal as sig_engine
from notifier import telegram

KST = timezone(timedelta(hours=9))


# ---------- 상태 저장 (직전 시그널 / 마지막 요약 날짜) ----------
def load_state(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"last_signal": {}, "last_summary_date": None}


def save_state(path, state):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except OSError as e:
        print(f"[state] 저장 실패: {e}")


# ---------- 대상 코인 선정 ----------
def resolve_targets(cfg):
    if cfg.COINS:
        return cfg.COINS  # 사용자가 명시한 코인은 그대로 존중
    try:
        # 제외 코인을 감안해 넉넉히 받은 뒤 필터 → 상위 TOP_N
        raw = bithumb.top_symbols_by_volume(cfg.QUOTE, cfg.TOP_N + len(cfg.EXCLUDE))
        return [s for s in raw if s not in cfg.EXCLUDE][:cfg.TOP_N]
    except bithumb.BithumbError as e:
        print(f"[targets] 상위 코인 조회 실패: {e}")
        return []


# ---------- 1회 분석 사이클 ----------
def run_cycle(cfg, state):
    targets = resolve_targets(cfg)
    print(f"[{datetime.now(KST):%Y-%m-%d %H:%M}] 분석 대상 {len(targets)}개: {', '.join(targets)}")

    results = []
    for sym in targets:
        try:
            candles = bithumb.get_candles(sym, cfg.QUOTE, cfg.CANDLE_INTERVAL)
            sig = sig_engine.analyze(candles, cfg)
            if sig:
                results.append((sym, sig))
        except bithumb.BithumbError as e:
            print(f"  - {sym} 조회 실패: {e}")
        bithumb.polite_sleep(cfg.REQUEST_SLEEP)

    results.sort(key=lambda x: x[1]["score"], reverse=True)

    # --- actionable 시그널 알림 ---
    sent = 0
    for sym, sig in results:
        actionable = sig["is_actionable"] or (cfg.ALERT_ON_WATCH and sig["label"] == "WATCH")
        if not actionable:
            continue
        prev = state["last_signal"].get(sym)
        if cfg.ALERT_MODE == "on_change" and prev == sig["label"]:
            continue  # 시그널 변화 없음 → 스킵
        msg = telegram.build_signal_message(sym, sig, cfg.CANDLE_INTERVAL)
        if telegram.send(cfg, msg):
            sent += 1
        bithumb.polite_sleep(0.1)

    # 모든 코인의 최신 시그널 상태 갱신
    for sym, sig in results:
        state["last_signal"][sym] = sig["label"]

    print(f"  → 알림 {sent}건 발송")
    return results


# ---------- 일일 요약 ----------
def maybe_send_summary(cfg, state, results):
    if cfg.DAILY_SUMMARY_HOUR < 0:
        return
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    if now.hour == cfg.DAILY_SUMMARY_HOUR and state.get("last_summary_date") != today:
        if results:
            msg = telegram.build_summary_message(results, cfg.CANDLE_INTERVAL)
            telegram.send(cfg, msg)
            state["last_summary_date"] = today
            print("  → 일일 요약 발송")


# ---------- 진입점 ----------
def main():
    Config.validate()
    cfg = Config
    state = load_state(cfg.STATE_FILE)

    mode = "DRY_RUN(콘솔)" if cfg.DRY_RUN else "텔레그램 발송"
    print("=" * 50)
    print("Daily Trading Signal — Bithumb 시그널 봇")
    print(f"모드: {mode} | 주기: {cfg.CHECK_INTERVAL_MIN}분 | 봉: {cfg.CANDLE_INTERVAL}")
    print(f"알림: {cfg.ALERT_MODE} | 일일요약: {cfg.DAILY_SUMMARY_HOUR}시(KST)")
    print("=" * 50)

    # 시작 시 1회 즉시 실행
    while True:
        try:
            results = run_cycle(cfg, state)
            maybe_send_summary(cfg, state, results)
            save_state(cfg.STATE_FILE, state)
        except Exception:
            print("[cycle] 예기치 못한 오류:\n" + traceback.format_exc())
        # ONESHOT=true 면 1회만 실행하고 종료 (테스트/cron용)
        if os.environ.get("ONESHOT", "").lower() == "true":
            print("ONESHOT 종료")
            break
        time.sleep(cfg.CHECK_INTERVAL_MIN * 60)


if __name__ == "__main__":
    main()
