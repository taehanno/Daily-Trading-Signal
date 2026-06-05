# ============================================
# 페이퍼 트레이딩 — 가상 진입/청산 자동 기록(실시간 포워드 테스트)
# ============================================
"""
실돈을 넣지 않고, BUY_IGNITION 시그널마다 '가상 포지션'을 열고 이후 봉에서
목표/손절/엔진청산/당일마감/시간손절로 닫는다. 누적 성적표(승률·기대값·PF)를
state.json 에 쌓아 여러 시장국면에 걸친 실제 성과를 모은다.

백테스트와 동일한 정산 규칙(보수적):
  · 청산 우선순위: 손절 → 목표 → 당일마감 → 엔진청산 → 시간손절
  · 같은 봉에서 손절·목표 동시 터치 시 손절 우선
  · 진입가 = 시그널 발생 봉 종가(라이브 근사), 청산에 왕복 수수료 반영

상태(state["paper"]):
  open   : {sym: {entry, entry_ts, entry_date, stop, target, bars, rvol, max_buy_krw}}
  stats  : {n, wins, sum, gp, gl}   누적(과거 trim돼도 유지)
  recent : 최근 청산 30건
"""
from datetime import datetime, timezone, timedelta

from exchanges import bithumb

KST = timezone(timedelta(hours=9))


def _kst_date_str(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, KST).date().isoformat()


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


def _exit_check(cfg, pos, bar, label, day_changed):
    """청산 사유/체결가 반환 또는 None. 우선순위: 손절→목표→당일마감→엔진→시간."""
    if pos.get("stop") and bar["low"] <= pos["stop"]:
        return "stop", pos["stop"]
    if pos.get("target") and bar["high"] >= pos["target"]:
        return "target", pos["target"]
    if day_changed:
        return "eod", bar["close"]
    if label == "EXIT_SCALP":
        return "engine_exit", bar["close"]
    if pos.get("bars", 0) >= cfg.PAPER_MAX_HOLD_BARS:
        return "time", bar["close"]
    return None


def _record(pap, sym, pos, price, net, reason, now_str):
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
        "bars": pos.get("bars", 0),
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

        pos["bars"] = pos.get("bars", 0) + 1
        day_changed = _kst_date_str(bar["ts"]) != pos.get("entry_date")
        ex = _exit_check(cfg, pos, bar, label, day_changed)
        if ex:
            reason, price = ex
            net = (price - pos["entry"]) / pos["entry"] - cfg.PAPER_FEE
            _record(pap, sym, pos, price, net, reason, now_str)
            del open_pos[sym]
            events.append({
                "type": "exit", "sym": sym, "net": net, "reason": reason,
                "entry": pos["entry"], "exit": price, "in": pos["entry_ts"],
                "out": now_str, "scorecard": scorecard(pap),
            })

    # 2) 신규 진입(BUY_IGNITION, 이미 보유 중이 아닌 종목)
    for sym, sig in sigs_by_sym.items():
        if sig["label"] != "BUY_IGNITION" or sym in open_pos:
            continue
        if sig.get("stop") is None or sig.get("target") is None:
            continue
        bar = market.get(sym, {}).get("bar")
        open_pos[sym] = {
            "entry": sig["price"], "entry_ts": now_str,
            "entry_date": _kst_date_str(bar["ts"]) if bar else None,
            "stop": sig["stop"], "target": sig["target"], "bars": 0,
            "rvol": sig.get("rvol"), "max_buy_krw": sig.get("max_buy_krw"),
        }
        events.append({"type": "entry", "sym": sym, "sig": sig})

    return events
