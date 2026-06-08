# ============================================
# 페이퍼 트레이딩 — 가상 진입/청산 자동 기록(실시간 포워드 테스트)
# ============================================
"""
실돈을 넣지 않고, 스윙 매수(BUY_IGNITION) 시그널마다 '가상 포지션'을 열고 이후
일봉에서 손절/엔진청산(추세전환)/시간손절(일)로 닫는다. 누적 성적표(승률·기대값·PF)를
state.json 에 쌓아 실시간(진짜 out-of-sample) 성과를 모은다.

백테스트와 동일한 정산 규칙(보수적):
  · 청산 우선순위: 손절 → (목표) → 엔진청산(추세전환) → 시간손절(일)
  · 진입가 = 시그널 발생 봉 종가(라이브 근사), 청산에 왕복 수수료 반영
  · 스윙이라 당일마감(EOD) 청산은 없음 — 며칠~몇주 보유

상태(state["paper"]):
  open   : {sym: {entry, entry_ts, entry_date, stop, target, exit_level, rvol, ...}}
  stats  : {n, wins, sum, gp, gl}   누적(과거 trim돼도 유지)
  recent : 최근 청산 30건
"""
from datetime import date, datetime, timezone, timedelta

from exchanges import bithumb

KST = timezone(timedelta(hours=9))


def _kst_date_str(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, KST).date().isoformat()


def _days_held(entry_date_str, bar_ts):
    """진입일 ~ 현재 봉 날짜(KST) 사이 일수. 파싱 실패 시 0."""
    try:
        return (date.fromisoformat(_kst_date_str(bar_ts))
                - date.fromisoformat(entry_date_str)).days
    except (ValueError, TypeError):
        return 0


def _init(state):
    pap = state.setdefault("paper", {})
    pap.setdefault("open", {})
    pap.setdefault("stats", {"n": 0, "wins": 0, "sum": 0.0, "gp": 0.0, "gl": 0.0})
    pap.setdefault("recent", [])
    return pap


def scorecard(pap):
    """누적 성적표 dict."""
    st = pap["stats"]
    n = st["n"]
    if n == 0:
        return {"n": 0, "wr": 0.0, "exp": 0.0, "pf": 0.0, "total": 0.0}
    gl = st["gl"]
    return {
        "n": n,
        "wr": st["wins"] / n * 100,
        "exp": st["sum"] / n * 100,
        "pf": (st["gp"] / gl) if gl > 0 else float("inf"),
        "total": st["sum"] * 100,
    }


def _exit_check(cfg, pos, bar, label, days_held):
    """청산 사유/체결가 반환 또는 None. 우선순위: 손절→목표→엔진(추세전환)→시간(일)."""
    if pos.get("stop") and bar["low"] <= pos["stop"]:
        return "stop", pos["stop"]
    if pos.get("target") and bar["high"] >= pos["target"]:
        return "target", pos["target"]
    if label == "EXIT_SCALP":
        return "engine_exit", bar["close"]
    if days_held >= cfg.PAPER_MAX_HOLD_DAYS:
        return "time", bar["close"]
    return None


def _record(pap, sym, pos, price, net, reason, now_str, days_held):
    st = pap["stats"]
    st["n"] += 1
    st["sum"] += net
    if net > 0:
        st["wins"] += 1
        st["gp"] += net
    else:
        st["gl"] += -net
    pap["recent"].append({
        "sym": sym, "entry": pos["entry"], "exit": price, "net": net,
        "reason": reason, "in": pos["entry_ts"], "out": now_str,
        "days": days_held,
    })
    pap["recent"] = pap["recent"][-30:]


def update(cfg, state, sigs_by_sym, market, now_str):
    """
    sigs_by_sym: {sym: sig}  이번 사이클 분석 결과
    market:      {sym: {"bar": <eval 봉 dict>, "label": str}}
    반환: 이벤트 리스트 [{"type":"entry"/"exit", ...}]  (main이 텔레로 렌더)
    """
    pap = _init(state)
    open_pos = pap["open"]
    events = []

    # 1) 보유 중인 가상 포지션 청산 점검
    for sym in list(open_pos.keys()):
        pos = open_pos[sym]
        m = market.get(sym)
        if m is None:
            # top-N 이탈 종목 — 개별 조회로 추적 유지
            try:
                candles = bithumb.get_candles(sym, cfg.QUOTE, cfg.CANDLE_INTERVAL)
                bithumb.polite_sleep(cfg.REQUEST_SLEEP)
            except bithumb.BithumbError:
                continue
            if len(candles) < 2:
                continue
            bar, label = candles[-2], None
        else:
            bar, label = m["bar"], m["label"]

        days_held = _days_held(pos.get("entry_date"), bar["ts"])
        ex = _exit_check(cfg, pos, bar, label, days_held)
        if ex:
            reason, price = ex
            net = (price - pos["entry"]) / pos["entry"] - cfg.PAPER_FEE
            _record(pap, sym, pos, price, net, reason, now_str, days_held)
            del open_pos[sym]
            events.append({
                "type": "exit", "sym": sym, "net": net, "reason": reason,
                "entry": pos["entry"], "exit": price, "in": pos["entry_ts"],
                "out": now_str, "days": days_held,
                "exit_level": pos.get("exit_level"),
                "scorecard": scorecard(pap),
            })

    # 2) 신규 진입(BUY_IGNITION, 이미 보유 중이 아닌 종목)
    for sym, sig in sigs_by_sym.items():
        if sig["label"] != "BUY_IGNITION" or sym in open_pos:
            continue
        if sig.get("stop") is None:      # 스윙은 목표 없음 — 손절만 필수
            continue
        bar = market.get(sym, {}).get("bar")
        open_pos[sym] = {
            "entry": sig["price"], "entry_ts": now_str,
            "entry_date": _kst_date_str(bar["ts"]) if bar else now_str.split(" ")[0],
            "stop": sig["stop"], "target": sig.get("target"),
            "exit_level": sig.get("exit_level"), "rvol": sig.get("rvol"),
            "max_buy_krw": sig.get("max_buy_krw"), "hold_text": sig.get("hold_text"),
        }
        events.append({"type": "entry", "sym": sym, "sig": sig})

    return events
