# ============================================
# 백테스트 — 평균회귀(mean-reversion) 받아치기 스캘핑 프로토타입
# ============================================
"""
검증된 사실: '돌파 추격'도 '눌림목 순방향'도 5분봉에선 엣지 0(둘 다 PF<1).
  → 이 시장이 5분 스케일에서 '평균회귀(mean-reversion)'적이라는 뜻.
  그래서 정반대 가설을 본다: 과매도 극단까지 '빠진' 것을 받아쳐 VWAP/평균으로의
  되돌림을 짧게 먹는다(fade). 추세 지속이 아니라 '되돌림'에 베팅.

진입(long, bar i 마감 기준 · 다음 봉 시가 체결 — 룩어헤드 방지):
  · 과매도   : RSI ≤ RSI_MAX (예 30)
  · VWAP 아래로 신장 : (close-VWAP)/VWAP ≤ -STRETCH (예 -0.8%, 평균에서 멀리 빠짐)
  · 반등 시작 양봉 : close > open  (떨어지는 칼 안 잡음 — 첫 회복봉 확인)
  · (옵션)캐피츌레이션 : 직전 봉 RVOL ≥ CAP_RVOL (투매 폭발)
  · (옵션)붕괴 제외 : 종가 > EMA_slow*(1-CRASH_TOL)  (구조 완전 붕괴면 패스)

청산(보수적, 동시터치 시 손절 우선):
  손절(받친 저점 아래) → 목표 → VWAP 복귀(되돌림 완료) → 당일마감 → 시간손절
  · 목표는 TARGET_TO_VWAP=1 이면 진입시 VWAP, 아니면 entry*(1+TARGET)

실행:
  python scripts/backtest_meanrev.py
  BT_SWEEP=1 python scripts/backtest_meanrev.py
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from config import Config
from exchanges import bithumb
from core import indicators as ind

KST = timezone(timedelta(hours=9))


def _kst_date(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, KST).date()


def _kst_hour(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, KST).hour


# ---------- 롤링 지표 시계열(인덱스 정렬, 앞쪽 None) ----------
def ema_aligned(values, period):
    s = ind.ema_series(values, period)
    return [None] * (period - 1) + s if s else [None] * len(values)


def rsi_series(closes, period=14):
    out = [None] * len(closes)
    if len(closes) < period + 1:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += d if d > 0 else 0.0
        losses += -d if d < 0 else 0.0
    ag, al = gains / period, losses / period
    out[period] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        g = d if d > 0 else 0.0
        l = -d if d < 0 else 0.0
        ag = (ag * (period - 1) + g) / period
        al = (al * (period - 1) + l) / period
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def rvol_series(vols, period=20):
    out = [None] * len(vols)
    for t in range(period, len(vols)):
        avg = sum(vols[t - period:t]) / period
        out[t] = (vols[t] / avg) if avg > 0 else None
    return out


def vwap_series(candles):
    out = [None] * len(candles)
    cur_date = None
    pv = v = 0.0
    for t, c in enumerate(candles):
        d = _kst_date(c["ts"])
        if d != cur_date:
            cur_date, pv, v = d, 0.0, 0.0
        typ = (c["high"] + c["low"] + c["close"]) / 3.0
        pv += typ * c["volume"]
        v += c["volume"]
        out[t] = (pv / v) if v > 0 else None
    return out


def precompute(candles, p):
    closes = [c["close"] for c in candles]
    vols = [c["volume"] for c in candles]
    arr = {
        "es": ema_aligned(closes, p["ema_slow"]),
        "rsi": rsi_series(closes, p["rsi_p"]),
        "rvol": rvol_series(vols, p["rvol_p"]),
        "vwap": vwap_series(candles),
    }
    arr["htf"] = ema_aligned(closes, p["htf_ema"]) if p.get("htf_ema", 0) else None
    return arr


def entry_at(candles, a, i, p):
    """bar i에서 받아치기 진입 조건 충족 시 (stop, vwap) 반환, 아니면 None."""
    es, rsi, vwap = a["es"][i], a["rsi"][i], a["vwap"][i]
    if None in (es, rsi, vwap):
        return None
    c = candles[i]
    if rsi > p["rsi_max"]:                                   # 과매도 아님
        return None
    if (c["close"] - vwap) / vwap > -p["stretch"]:           # VWAP 아래로 충분히 안 빠짐
        return None
    if not (c["close"] > c["open"]):                         # 첫 회복 양봉 아님
        return None
    if p.get("cap_rvol", 0) > 0:                             # 투매 캐피츌레이션
        rv = a["rvol"][i]
        if rv is None or rv < p["cap_rvol"]:
            return None
    if p.get("crash_tol", 0) > 0:                            # 구조 완전 붕괴 제외
        if c["close"] < es * (1 - p["crash_tol"]):
            return None
    if a.get("htf") is not None:                             # 상위추세 우호(긴 EMA 위에서만 받아침)
        h = a["htf"][i]
        if h is None or c["close"] < h:
            return None
    lo0 = max(0, i - p["low_lookback"] + 1)
    pb_low = min(candles[t]["low"] for t in range(lo0, i + 1))
    return pb_low * (1 - p["stop_buf"]), vwap


def simulate(candles, p):
    a = precompute(candles, p)
    trades = []
    n = len(candles)
    start = max(p["ema_slow"], p["rsi_p"] + 1, p["rvol_p"]) + 2
    i = start
    while i < n - 1:
        res = entry_at(candles, a, i, p)
        if res is None:
            i += 1
            continue
        stop, entry_vwap = res
        entry_idx = i + 1
        entry = candles[entry_idx]["open"] * (1 + p["slip"])
        if stop >= entry:
            i += 1
            continue
        if p.get("target_to_vwap"):
            target = max(entry_vwap, entry * (1 + p["min_target"]))
        else:
            target = entry * (1 + p["target"])
        day = _kst_date(candles[entry_idx]["ts"])
        ep = ei = reason = None
        for j in range(entry_idx, min(n, entry_idx + p["max_hold"] + 1)):
            b = candles[j]
            if b["low"] <= stop:
                ep, ei, reason = stop, j, "stop"
                break
            if b["high"] >= target:
                ep, ei, reason = target, j, "target"
                break
            # VWAP 복귀 시 되돌림 완료 — 종가 청산(목표 미달이어도 평균회귀 달성)
            if p.get("exit_on_vwap") and j > entry_idx:
                vw = a["vwap"][j]
                if vw is not None and b["close"] >= vw:
                    ep, ei, reason = b["close"], j, "vwap_revert"
                    break
            if _kst_date(b["ts"]) != day:
                ep, ei, reason = b["open"], j, "eod"
                break
        if ep is None:
            ei = min(n - 1, entry_idx + p["max_hold"])
            ep, reason = candles[ei]["close"], "time"
        net = (ep - entry) / entry - p["fee"]
        trades.append({
            "hold": ei - entry_idx, "net": net, "reason": reason,
            "win": net > 0, "hour": _kst_hour(candles[entry_idx]["ts"]),
        })
        i = ei + 1
    return trades


def stats(trades):
    if not trades:
        return None
    n = len(trades)
    wins = [t for t in trades if t["win"]]
    gp = sum(t["net"] for t in wins)
    gl = -sum(t["net"] for t in trades if not t["win"])
    return {
        "n": n, "wr": len(wins) / n * 100,
        "exp": sum(t["net"] for t in trades) / n * 100,
        "pf": (gp / gl) if gl > 0 else float("inf"),
        "total": sum(t["net"] for t in trades) * 100,
        "hold": sum(t["hold"] for t in trades) / n,
    }


DEFAULT = {
    "ema_slow": 21, "rsi_p": 14, "rvol_p": 20,
    "rsi_max": 30.0, "stretch": 0.008, "low_lookback": 3,
    "cap_rvol": 0.0, "crash_tol": 0.05,
    "target": 0.012, "min_target": 0.006, "stop_buf": 0.001,
    "target_to_vwap": True, "exit_on_vwap": True,
    "htf_ema": 0,   # 0=off. >0 이면 그 길이 EMA 위에서만 진입(상위추세 우호)
    "max_hold": int(os.environ.get("BT_MAX_HOLD", 24)),
    "fee": float(os.environ.get("BT_FEE", 0.001)),
    "slip": float(os.environ.get("BT_SLIP", 0.0005)),
}


def fetch_all(cfg, targets):
    data = {}
    for sym in targets:
        try:
            c = bithumb.get_candles(sym, cfg.QUOTE, cfg.CANDLE_INTERVAL)
        except bithumb.BithumbError:
            continue
        if len(c) >= 100:
            data[sym] = c
        bithumb.polite_sleep(cfg.REQUEST_SLEEP)
    return data


def run_one(data, p, by_detail=False):
    allt = []
    per = {}
    for sym, c in data.items():
        tr = simulate(c, p)
        per[sym] = stats(tr)
        allt.extend(tr)
    s = stats(allt)
    if by_detail and s:
        for sym in sorted(per, key=lambda k: -(per[k]["total"] if per[k] else 0)):
            ss = per[sym]
            if ss:
                print(f"  {sym:<8} {ss['n']:>3}건 · 승률 {ss['wr']:>5.1f}% · "
                      f"평균 {ss['exp']:+.2f}% · 누적 {ss['total']:+.1f}% · PF {ss['pf']:.2f}")
        reasons = {}
        for t in allt:
            reasons.setdefault(t["reason"], []).append(t)
        print("  ── 청산 사유 ──")
        for r, ts in sorted(reasons.items(), key=lambda x: -len(x[1])):
            wr = sum(t["win"] for t in ts) / len(ts) * 100
            print(f"     {r:<12}{len(ts):>3}건 · 승률 {wr:5.1f}%")
    return s, allt


def main():
    cfg = Config
    targets = cfg.COINS or bithumb.top_symbols_by_volume(cfg.QUOTE, cfg.TOP_N)
    print(f"데이터 수신 중… 상위 {len(targets)}개")
    data = fetch_all(cfg, targets)
    if not data:
        print("데이터 없음")
        return
    span = next(iter(data.values()))
    span_d = (span[-1]["ts"] - span[0]["ts"]) / 1000 / 86400
    print(f"수신 {len(data)}개 · 약 {span_d:.1f}일 · 수수료 {DEFAULT['fee'] * 100:.2f}%(왕복)\n")

    if os.environ.get("BT_SPLIT") == "1":
        # 과적합 방지: 앞 70% '학습', 뒤 30% '검증'으로 시간 분리. 둘 다 +인 것만 신뢰.
        # 선별(selectivity) 가설 — 건당 엣지를 수수료 위로 올리는 게 목표.
        V = {"target_to_vwap": True, "exit_on_vwap": True, "crash_tol": 0.05}
        combos = [
            ("기준 RSI30·신장0.8%", {**V}),
            ("깊은과매도 RSI25", {**V, "rsi_max": 25.0}),
            ("깊은과매도 RSI20", {**V, "rsi_max": 20.0}),
            ("큰신장 1.5%", {**V, "stretch": 0.015}),
            ("큰신장 2.0%", {**V, "stretch": 0.020}),
            ("상위추세 EMA50위", {**V, "htf_ema": 50}),
            ("상위추세 EMA100위", {**V, "htf_ema": 100}),
            ("RSI25+신장1.5%", {**V, "rsi_max": 25.0, "stretch": 0.015}),
            ("RSI25+상위추세EMA50", {**V, "rsi_max": 25.0, "htf_ema": 50}),
            ("RSI25+신장1.5%+추세EMA50", {**V, "rsi_max": 25.0, "stretch": 0.015, "htf_ema": 50}),
        ]
        train = {s: c[:int(len(c) * 0.7)] for s, c in data.items()}
        test = {s: c[int(len(c) * 0.7):] for s, c in data.items()}
        td = (train[next(iter(train))][-1]["ts"] - train[next(iter(train))][0]["ts"]) / 1000 / 86400
        ed = (test[next(iter(test))][-1]["ts"] - test[next(iter(test))][0]["ts"]) / 1000 / 86400
        print(f"학습 {td:.0f}일 / 검증 {ed:.0f}일 · 수수료 {DEFAULT['fee'] * 100:.3f}%(왕복)")
        print("=" * 92)
        print(f"{'조합':<30}{'│ 학습 건수':>10}{'기대값':>9}{'PF':>6}{'  │ 검증 건수':>12}{'기대값':>9}{'PF':>6}")
        print("-" * 92)
        for name, ov in combos:
            p = dict(DEFAULT)
            p.update(ov)
            strn, _ = run_one(train, p)
            ste, _ = run_one(test, p)
            def cell(s):
                return (f"{s['n']:>6}{s['exp']:>+9.3f}%{s['pf']:>6.2f}") if s else f"{'0':>6}{'-':>16}"
            print(f"{name:<30}│{cell(strn)}  │{cell(ste)}")
        print("=" * 92)
        print("※ 학습·검증 둘 다 PF>1 이고 검증 기대값>0 인 조합만 신뢰. 한쪽만 +면 과적합.")
        return

    if os.environ.get("BT_SWEEP") == "1":
        # 2차 정밀 스윕: VWAP복귀 청산을 고정하고(엣지 원천) 진입필터를 변주
        V = {"target_to_vwap": True, "exit_on_vwap": True}
        combos = [
            ("기준 RSI30·신장0.8%", {**V}),
            ("RSI35·신장0.8%", {**V, "rsi_max": 35.0}),
            ("RSI35·신장0.5%", {**V, "rsi_max": 35.0, "stretch": 0.005}),
            ("RSI30·신장0.8%·손절버퍼0.3%", {**V, "stop_buf": 0.003}),
            ("RSI30·신장0.8%·저점룩백5", {**V, "low_lookback": 5}),
            ("RSI30·신장0.8%·붕괴제외5%", {**V, "crash_tol": 0.05}),
            ("RSI35·신장0.5%·붕괴제외5%·버퍼0.3%", {**V, "rsi_max": 35.0, "stretch": 0.005,
                "crash_tol": 0.05, "stop_buf": 0.003}),
            ("RSI35·신장0.5%·최소목표0.4%·시간손절36", {**V, "rsi_max": 35.0, "stretch": 0.005,
                "min_target": 0.004, "max_hold": 36}),
        ]
        print("=" * 78)
        print(f"{'조합':<38}{'건수':>5}{'승률':>8}{'기대값':>9}{'PF':>6}{'누적':>9}")
        print("-" * 78)
        for name, ov in combos:
            p = dict(DEFAULT)
            p.update(ov)
            s, _ = run_one(data, p)
            if s:
                print(f"{name:<38}{s['n']:>5}{s['wr']:>7.1f}%{s['exp']:>+8.3f}%"
                      f"{s['pf']:>6.2f}{s['total']:>+8.1f}%")
            else:
                print(f"{name:<38}{'0':>5}  (진입 없음)")
        print("=" * 78)
        print("※ 10일 단일 표본 — 양수여도 과적합 주의. 실거래 전 추가 검증 필수.")
    else:
        print("기본 파라미터 상세:")
        s, _ = run_one(data, dict(DEFAULT), by_detail=True)
        print("=" * 60)
        if s:
            print(f"📊 전체: {s['n']}건 · 승률 {s['wr']:.1f}% · 기대값 {s['exp']:+.3f}% · "
                  f"PF {s['pf']:.2f} · 누적 {s['total']:+.1f}% · 평균보유 {s['hold']:.1f}봉")
        else:
            print("진입 0건")


if __name__ == "__main__":
    main()
