# ============================================
# 백테스트 — 눌림목(pullback) 진입 전략 프로토타입
# ============================================
"""
'돌파 추격'은 엣지 0으로 검증됨(scripts/backtest.py). 그 정반대인 '눌림목 진입'을 검증한다.

아이디어: 거래량 서지로 한 번 치고 올라간(in-play) 상승추세 종목이, EMA9까지
  '눌렸다가' 다시 양봉으로 회복할 때 진입. 추격이 아니라 되돌림의 끝을 산다.
  → 손절을 눌림 저점 바로 아래에 둘 수 있어(가깝고 의미있음) 손익비가 개선될 여지.

진입(bar i 마감 기준, 다음 봉 시가 체결 — 룩어헤드 방지):
  · 상승추세 : EMA_fast > EMA_slow
  · VWAP 위 : close > VWAP(당일)
  · in-play : 최근 SURGE_LOOKBACK봉 내 RVOL ≥ SURGE_TRIGGER 있었음
  · 눌림    : 최근 PB_LOOKBACK봉 저점이 EMA_fast 터치(<= EMA_fast*(1+TOUCH_TOL))
  · 회복    : 양봉(close>open) & close > EMA_fast
  · 안과열  : (close-EMA_fast)/EMA_fast ≤ MAX_EXT_EMA  (EMA 근처, 멀리 안 뜸)
  · RSI     : RSI_MIN ~ RSI_MAX (과열에서 식은 구간)

청산(보수적): 손절(눌림저점 아래) → 목표(+TARGET) → 당일마감 → 시간손절. 동시터치 시 손절 우선.

실행:
  python scripts/backtest_pullback.py          # 기본 1세트
  BT_SWEEP=1 python scripts/backtest_pullback.py  # 조합 스윕
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


# ---------- 롤링 지표 시계열(인덱스 정렬, 앞쪽은 None) ----------
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


# ---------- 눌림목 진입 판정 ----------
def precompute(candles, p):
    closes = [c["close"] for c in candles]
    vols = [c["volume"] for c in candles]
    arr = {
        "ef": ema_aligned(closes, p["ema_fast"]),
        "es": ema_aligned(closes, p["ema_slow"]),
        "rsi": rsi_series(closes, p["rsi_p"]),
        "rvol": rvol_series(vols, p["rvol_p"]),
        "vwap": vwap_series(candles),
    }
    arr["htf"] = ema_aligned(closes, p["htf_ema"]) if p.get("htf_ema", 0) else None
    return arr


def entry_at(candles, ind_arr, i, p):
    """bar i에서 눌림목 진입 조건 충족 시 stop 레벨 반환, 아니면 None."""
    ef, es = ind_arr["ef"][i], ind_arr["es"][i]
    rsi, vwap = ind_arr["rsi"][i], ind_arr["vwap"][i]
    if None in (ef, es, rsi, vwap):
        return None
    c = candles[i]
    if not (ef > es):                       # 단기 상승추세
        return None
    # 상위 시간축(HTF) 추세 필터: 긴 EMA 위 + 그 EMA 상승 중 (빠지는 코인 제외)
    if ind_arr["htf"] is not None:
        h, hp = ind_arr["htf"][i], ind_arr["htf"][i - 1]
        if h is None or hp is None or not (c["close"] > h and h > hp):
            return None
    if not (c["close"] > vwap):             # VWAP 위
        return None
    # in-play: 최근 서지
    surge = False
    for t in range(max(0, i - p["surge_lookback"] + 1), i + 1):
        r = ind_arr["rvol"][t]
        if r is not None and r >= p["surge_trigger"]:
            surge = True
            break
    if not surge:
        return None
    # 눌림: 최근 PB_LOOKBACK봉 저점이 EMA_fast 터치
    lo0 = max(0, i - p["pb_lookback"] + 1)
    pb_low = min(candles[t]["low"] for t in range(lo0, i + 1))
    if pb_low > ef * (1 + p["touch_tol"]):
        return None
    if not (c["close"] > c["open"] and c["close"] > ef):   # 양봉 회복
        return None
    if (c["close"] - ef) / ef > p["max_ext_ema"]:          # 과열 아님
        return None
    if not (p["rsi_min"] <= rsi <= p["rsi_max"]):
        return None
    return pb_low * (1 - p["stop_buf"])                     # 손절: 눌림 저점 아래


# ---------- 시뮬레이션 ----------
def simulate(candles, p):
    ind_arr = precompute(candles, p)
    trades = []
    n = len(candles)
    start = max(p["ema_slow"], p["rsi_p"] + 1, p["rvol_p"] + p["surge_lookback"]) + 2
    i = start
    while i < n - 1:
        stop = entry_at(candles, ind_arr, i, p)
        if stop is None:
            i += 1
            continue
        entry_idx = i + 1
        entry = candles[entry_idx]["open"] * (1 + p["slip"])
        if stop >= entry:
            i += 1
            continue
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
    "ema_fast": 9, "ema_slow": 21, "rsi_p": 14, "rvol_p": 20,
    "surge_lookback": 10, "surge_trigger": 2.5,
    "pb_lookback": 3, "touch_tol": 0.002, "max_ext_ema": 0.008,
    "rsi_min": 40.0, "rsi_max": 65.0,
    "target": 0.015, "stop_buf": 0.001,
    "htf_ema": 0,   # 0=off. >0 이면 해당 길이 EMA로 상위추세 필터
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
        print("  ── 시간대(KST) ──")
        byh = {}
        for t in allt:
            byh.setdefault(t["hour"], []).append(t)
        for h in sorted(byh):
            ts = byh[h]
            wr = sum(t["win"] for t in ts) / len(ts) * 100
            avg = sum(t["net"] for t in ts) / len(ts) * 100
            key = " 🔥" if h in Config.KEY_HOURS else ""
            print(f"     {h:02d}시{key:<2}{len(ts):>3}건 · 승률 {wr:5.1f}% · 평균 {avg:+.2f}%")
    return s, allt


def main():
    cfg = Config
    targets = cfg.COINS or bithumb.top_symbols_by_volume(cfg.QUOTE, cfg.TOP_N)
    print(f"데이터 수신 중… 상위 {len(targets)}개")
    data = fetch_all(cfg, targets)
    span = next(iter(data.values()))
    span_d = (span[-1]["ts"] - span[0]["ts"]) / 1000 / 86400
    print(f"수신 {len(data)}개 · 약 {span_d:.1f}일 · 수수료 {DEFAULT['fee'] * 100:.2f}%(왕복)\n")

    if os.environ.get("BT_SWEEP") == "1":
        combos = [
            ("기본(필터 없음)", {}),
            ("HTF필터 EMA50", {"htf_ema": 50}),
            ("HTF필터 EMA100", {"htf_ema": 100}),
            ("HTF100+목표2.5%", {"htf_ema": 100, "target": 0.025}),
            ("HTF100+RVOL3.5", {"htf_ema": 100, "surge_trigger": 3.5}),
            ("HTF100+목표2.5%+RVOL4", {"htf_ema": 100, "target": 0.025, "surge_trigger": 4.0}),
            ("HTF50+목표2%+손절버퍼0.3%", {"htf_ema": 50, "target": 0.020, "stop_buf": 0.003}),
            ("HTF100+목표3%+시간손절36", {"htf_ema": 100, "target": 0.030, "max_hold": 36}),
        ]
        print("=" * 76)
        print(f"{'조합':<34}{'건수':>5}{'승률':>8}{'기대값':>9}{'PF':>6}{'누적':>9}")
        print("-" * 76)
        for name, ov in combos:
            p = dict(DEFAULT)
            p.update(ov)
            s, _ = run_one(data, p)
            if s:
                print(f"{name:<34}{s['n']:>5}{s['wr']:>7.1f}%{s['exp']:>+8.3f}%"
                      f"{s['pf']:>6.2f}{s['total']:>+8.1f}%")
            else:
                print(f"{name:<34}{'0':>5}  (진입 없음)")
        print("=" * 76)
        print("※ 10일 단일 표본 — 양수여도 과적합 주의.")
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
