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
from core import paper as paper_engine
from notifier import telegram

KST = timezone(timedelta(hours=9))


# ---------- 상태 저장 (직전 시그널 / 마지막 요약 날짜) ----------
def load_state(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    # 구버전 state.json 호환: 누락 키 보강
    state.setdefault("last_signal", {})
    state.setdefault("last_summary_date", None)
    state.setdefault("signal_since", {})  # {symbol: "YYYY-MM-DD HH:MM"} 현재 시그널 발생 시각
    return state


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


# ---------- 호가창 유동성 → 권장 최대 매수금액 ----------
def attach_liquidity(cfg, sym, sig):
    """매수 시그널에 호가창 기반 유동성/권장 최대 매수금액을 붙인다(실패 시 조용히 패스)."""
    try:
        ob = bithumb.get_orderbook(sym, cfg.QUOTE)
        liq = bithumb.ask_liquidity_within(ob["asks"], cfg.LIQUIDITY_SLIPPAGE)
    except bithumb.BithumbError as e:
        print(f"  - {sym} 호가 조회 실패: {e}")
        liq = None
    bithumb.polite_sleep(cfg.REQUEST_SLEEP)
    if liq is None:
        return
    sig["liquidity_krw"] = liq                                  # 슬리피지 이내 매도물량(KRW)
    sig["max_buy_krw"] = liq * cfg.LIQUIDITY_SAFETY             # 권장 최대 매수금액
    sig["liquidity_slippage"] = cfg.LIQUIDITY_SLIPPAGE
    sig["thin_book"] = sig["max_buy_krw"] < cfg.THIN_BOOK_KRW   # 호가 얇음 경고


# ---------- 1회 분석 사이클 ----------
def run_cycle(cfg, state):
    targets = resolve_targets(cfg)
    print(f"[{datetime.now(KST):%Y-%m-%d %H:%M}] 분석 대상 {len(targets)}개: {', '.join(targets)}")

    results = []
    market = {}   # {sym: {"bar": <eval 봉>, "label": str}} — 페이퍼 청산 점검용
    for sym in targets:
        try:
            candles = bithumb.get_candles(sym, cfg.QUOTE, cfg.CANDLE_INTERVAL)
            sig = sig_engine.analyze(candles, cfg)
            if sig:
                # 매수 시그널이면 호가창 유동성으로 '권장 최대 매수금액' 산정
                if sig["label"] in sig_engine.BUY_SIDE:
                    attach_liquidity(cfg, sym, sig)
                results.append((sym, sig))
                if len(candles) >= 2:
                    market[sym] = {"bar": candles[-2], "label": sig["label"]}
        except bithumb.BithumbError as e:
            print(f"  - {sym} 조회 실패: {e}")
        bithumb.polite_sleep(cfg.REQUEST_SLEEP)

    results.sort(key=lambda x: x[1]["score"], reverse=True)

    now = datetime.now(KST)
    now_str = now.strftime("%Y-%m-%d %H:%M")
    # 직전 시그널 스냅샷(상태 갱신 전에 떠서 변화 판정에 사용)
    prev_signals = dict(state["last_signal"])
    since = state["signal_since"]

    # 시그널이 '바뀐' 종목은 발생 시각을 지금으로 기록 (이후 동일하면 유지)
    for sym, sig in results:
        if prev_signals.get(sym) != sig["label"]:
            since[sym] = now_str

    sent = 0
    # --- 페이퍼 트레이딩: 가상 진입/청산 기록 + 알림 (단건 시그널 알림을 대체) ---
    if cfg.PAPER_TRADING:
        sigs_by_sym = {sym: sig for sym, sig in results}
        events = paper_engine.update(cfg, state, sigs_by_sym, market, now_str)
        for ev in events:
            if ev["type"] == "entry":
                msg = telegram.build_paper_entry(ev["sym"], ev["sig"], cfg.CANDLE_INTERVAL)
            else:
                msg = telegram.build_paper_exit(ev)
            if telegram.send(cfg, msg):
                sent += 1
            bithumb.polite_sleep(0.1)
    # --- actionable 단건 알림 (페이퍼/HOURLY_STATUS 모드에서는 생략) ---
    elif not cfg.HOURLY_STATUS:
        for sym, sig in results:
            actionable = sig["is_actionable"] or (cfg.ALERT_ON_WATCH and sig["label"] == "WATCH")
            if not actionable:
                continue
            if cfg.ALERT_MODE == "on_change" and prev_signals.get(sym) == sig["label"]:
                continue  # 시그널 변화 없음 → 스킵
            msg = telegram.build_signal_message(sym, sig, cfg.CANDLE_INTERVAL)
            if telegram.send(cfg, msg):
                sent += 1
            bithumb.polite_sleep(0.1)

    # 모든 코인의 최신 시그널 상태 갱신
    for sym, sig in results:
        state["last_signal"][sym] = sig["label"]
    # 더 이상 대상이 아닌(top-N 이탈) 종목의 발생시각 정리 — 상태 비대화 방지
    live = {sym for sym, _ in results}
    for sym in [s for s in since if s not in live]:
        since.pop(sym, None)

    # --- 매시간 전 종목 현황 다이제스트 (변화 없어도 항상 1건) ---
    if cfg.HOURLY_STATUS:
        if results:
            msg = telegram.build_status_message(
                results, since, prev_signals, cfg.CANDLE_INTERVAL, now_str)
        else:
            msg = f"📡 시그널 현황 {now_str} — 분석 대상/데이터 없음(거래소 조회 실패 가능)"
        if telegram.send(cfg, msg):
            sent += 1

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
