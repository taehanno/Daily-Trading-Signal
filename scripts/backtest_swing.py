# ============================================
# 백테스트 — 일봉 스윙(추세추종/돌파/눌림목) 프로토타입
# ============================================
"""
단타(5분·1시간)는 수수료에 엣지가 먹혀 본전 게임으로 확인됨. 그래서 시간축을 올려
'며칠~몇주 보유'하는 스윙을 본다. 스윙은 한 번의 큰 추세를 먹으므로 수수료(왕복 0.08%)
부담이 무의미해지고, 5분 cron 지연·오버나잇 회피 제약에서도 자유롭다.

검증 아키타입(롱온리, 현물):
  · trend    : EMA_fast가 EMA_slow를 상향 돌파(골든크로스)에 진입 → 데드크로스에 청산
  · breakout : 직전 DON_N일 고점 돌파(돈치안)에 진입 → DON_EXIT일 저점 이탈에 청산(터틀식)
  · pullback : 상승추세(EMA_fast>EMA_slow)에서 EMA_fast로 눌렸다 양봉 회복 시 진입

공통 청산: ATR 손절(진입가-ATR×배수, 옵션 트레일링) / 목표(옵션) / 시간손절 / 추세·채널 이탈
정산(보수적): 다음 날 시가 진입(룩어헤드 방지), 같은 봉 손절·목표 동시면 손절 우선,
  진입 슬리피지 + 청산 왕복 수수료 반영.

실행:
  python scripts/backtest_swing.py            # 조합 스윕
  SWING_INTERVAL=24h BT_FEE=0.0008 python scripts/backtest_swing.py
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
INTERVAL = os.environ.get("SWING_INTERVAL", "24h")
FEE = float(os.environ.get("BT_FEE", 0.0008))    # 왕복 수수료(빗썸 쿠폰 0.04%×2)
SLIP = float(os.environ.get("BT_SLIP", 0.001))   # 일봉 시가 진입 슬리피지


def ema_aligned(values, period):
    s = ind.ema_series(values, period)
    return [None] * (period - 1) + s if s else [None] * len(values)


def rvol_aligned(candles, period):
    """현재 거래량 / 직전 period일 평균 거래량(RVOL) 시계열. = '지금 수급/뉴스 유입' 강도."""
    vols = [c["volume"] for c in candles]
    out = [None] * len(candles)
    for i in range(period, len(vols)):
        avg = sum(vols[i - period:i]) / period
        out[i] = (vols[i] / avg) if avg > 0 else None
    return out


def atr_aligned(candles, period):
    """Wilder ATR 시계열(인덱스 정렬, 앞쪽 None)."""
    out = [None] * len(candles)
    if len(candles) < period + 1:
        return out
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[:period]) / period
    out[period] = atr
    for k in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[k]) / period
        out[k + 1] = atr
    return out


def simulate(candles, p):
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    ef = ema_aligned(closes, p["ema_fast"])
    es = ema_aligned(closes, p["ema_slow"])
    atr = atr_aligned(candles, p["atr_p"])
    rvol = rvol_aligned(candles, p.get("rvol_p", 20)) if p.get("rvol_min", 0) > 0 else None

    trades = []
    n = len(candles)
    start = max(p["ema_slow"], p["don_n"], p["atr_p"], p.get("rvol_p", 20)) + 2
    i = start
    while i < n - 1:
        sig = False
        if p["mode"] == "trend":
            if None not in (ef[i], es[i], ef[i - 1], es[i - 1]):
                sig = ef[i] > es[i] and ef[i - 1] <= es[i - 1]      # 골든크로스
        elif p["mode"] == "breakout":
            don_h = max(highs[i - p["don_n"]:i])                    # 직전 N일 고점
            sig = closes[i] > don_h and (es[i] is not None and ef[i] is not None and ef[i] > es[i])
        elif p["mode"] == "pullback":
            if None not in (ef[i], es[i]):
                sig = ef[i] > es[i] and lows[i] <= ef[i] and closes[i] > candles[i]["open"]
        if sig and rvol is not None:                            # 현재 거래량 급증 확인(뉴스/수급)
            rv = rvol[i]
            if rv is None or rv < p["rvol_min"]:
                sig = False
        if not sig:
            i += 1
            continue

        a0 = atr[i]
        if a0 is None:
            i += 1
            continue
        entry_idx = i + 1
        entry = candles[entry_idx]["open"] * (1 + SLIP)
        stop = entry - p["atr_stop"] * a0
        if stop >= entry:
            i += 1
            continue
        target = entry * (1 + p["target"]) if p.get("target", 0) > 0 else None
        highest = entry

        ep = ei = reason = None
        for j in range(entry_idx, min(n, entry_idx + p["max_hold"] + 1)):
            b = candles[j]
            if p.get("trail"):
                highest = max(highest, b["high"])
                stop = max(stop, highest - p["atr_stop"] * a0)      # 샹들리에 트레일
            if b["low"] <= stop:
                ep, ei, reason = stop, j, "stop"
                break
            if target and b["high"] >= target:
                ep, ei, reason = target, j, "target"
                break
            if j > entry_idx:
                if p["mode"] in ("trend", "pullback"):
                    if ef[j] is not None and es[j] is not None and ef[j] < es[j]:
                        ep, ei, reason = b["close"], j, "trend_exit"   # 데드크로스(시장 전환)
                        break
                elif p["mode"] == "breakout":
                    don_l = min(lows[j - p["don_exit"]:j])
                    if b["close"] < don_l:
                        ep, ei, reason = b["close"], j, "chan_exit"
                        break
        if ep is None:
            ei = min(n - 1, entry_idx + p["max_hold"])
            ep, reason = candles[ei]["close"], "time"

        net = (ep - entry) / entry - FEE
        hold_days = (candles[ei]["ts"] - candles[entry_idx]["ts"]) / 1000 / 86400
        trades.append({"net": net, "reason": reason, "win": net > 0, "days": hold_days})
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
        "days": sum(t["days"] for t in trades) / n,
        "avg_win": (gp / len(wins) * 100) if wins else 0,
        "avg_loss": (-gl / (n - len(wins)) * 100) if (n - len(wins)) else 0,
    }


def fetch_all(targets):
    data = {}
    for sym in targets:
        try:
            c = bithumb.get_candles(sym, Config.QUOTE, INTERVAL)
        except bithumb.BithumbError:
            continue
        if len(c) >= 120:
            data[sym] = c
        bithumb.polite_sleep(Config.REQUEST_SLEEP)
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
                      f"평균 {ss['exp']:+.2f}% · 누적 {ss['total']:+.1f}% · PF {ss['pf']:.2f} · "
                      f"보유 {ss['days']:.0f}일")
        reasons = {}
        for t in allt:
            reasons.setdefault(t["reason"], []).append(t)
        print("  ── 청산 사유 ──")
        for r, ts in sorted(reasons.items(), key=lambda x: -len(x[1])):
            wr = sum(t["win"] for t in ts) / len(ts) * 100
            avg = sum(t["net"] for t in ts) / len(ts) * 100
            print(f"     {r:<12}{len(ts):>3}건 · 승률 {wr:5.1f}% · 평균 {avg:+.2f}%")
    return s, allt


DEFAULT = {
    "mode": "trend", "ema_fast": 20, "ema_slow": 50,
    "don_n": 20, "don_exit": 10, "atr_p": 14, "atr_stop": 3.0,
    "trail": False, "target": 0.0, "max_hold": 60,
    "rvol_p": 20, "rvol_min": 0.0,   # rvol_min>0 이면 진입봉 거래량이 평균 대비 그 배수 이상이어야
}


def main():
    cfg = Config
    targets = cfg.COINS or bithumb.top_symbols_by_volume(cfg.QUOTE, cfg.TOP_N)
    print(f"데이터 수신 중… 상위 {len(targets)}개 ({INTERVAL}봉)")
    data = fetch_all(targets)
    if not data:
        print("데이터 없음")
        return
    span = next(iter(data.values()))
    span_d = (span[-1]["ts"] - span[0]["ts"]) / 1000 / 86400
    print(f"수신 {len(data)}개 · 약 {span_d:.0f}일 · 수수료 {FEE * 100:.3f}%(왕복) · 슬리피지 {SLIP * 100:.2f}%\n")

    if os.environ.get("BT_VOL") == "1":
        # "거래량 터진 돌파만 골라도 수익이 유지되나?" = 모든 신호 안 받아도 되나?
        # 돌파+추세 각각에 RVOL 임계값을 올려가며: 거래 수·누적·PF 변화 + 유지율(vs 무필터).
        bases = [
            ("돌파 돈치안20/10", {"mode": "breakout", "don_n": 20, "don_exit": 10}),
            ("추세 EMA10/30", {"mode": "trend", "ema_fast": 10, "ema_slow": 30}),
        ]
        thresholds = [0.0, 1.5, 2.0, 2.5, 3.0, 4.0]
        for bname, bov in bases:
            print(f"\n■ {bname} — 진입봉 거래량(RVOL) 필터별")
            print("-" * 88)
            print(f"{'RVOL≥':>7}{'건수':>7}{'(유지율)':>9}{'승률':>8}{'기대값':>10}{'PF':>7}"
                  f"{'누적':>10}{'(수익유지율)':>11}")
            base_total = base_n = None
            for th in thresholds:
                p = dict(DEFAULT)
                p.update(bov)
                p["rvol_min"] = th
                s, _ = run_one(data, p)
                if not s:
                    print(f"{th:>6.1f}{'0':>8}")
                    continue
                if base_total is None:
                    base_total, base_n = s["total"], s["n"]
                tk = s["n"] / base_n * 100
                pk = s["total"] / base_total * 100 if base_total else 0
                tag = "  ← 무필터" if th == 0.0 else ""
                print(f"{th:>6.1f}{s['n']:>8}{tk:>8.0f}%{s['wr']:>7.1f}%{s['exp']:>+9.2f}%"
                      f"{s['pf']:>7.2f}{s['total']:>+9.1f}%{pk:>9.0f}%{tag}")
            print("-" * 88)
        print("\n※ '수익유지율'이 '거래유지율'보다 높으면 → 거래량 터진 돌파에 수익이 몰림")
        print("   = 모든 신호 안 받고 거래량 급증한 것만 골라도 됨(선별 효과).")
        return

    if os.environ.get("BT_SPLIT") == "1":
        # 시간 분리: 앞 65% 학습 / 뒤 35% 검증. 둘 다 PF>1·검증 기대값>0 이면 국면운 아닌 진짜 엣지.
        combos = [
            ("돌파 돈치안20/10", {"mode": "breakout", "don_n": 20, "don_exit": 10}),
            ("돌파 돈치안20/10·RVOL2.0 ★", {"mode": "breakout", "don_n": 20, "don_exit": 10, "rvol_min": 2.0}),
            ("돌파 돈치안20/10·RVOL2.5", {"mode": "breakout", "don_n": 20, "don_exit": 10, "rvol_min": 2.5}),
            ("돌파 돈치안20/10·RVOL2·트레일", {"mode": "breakout", "don_n": 20, "don_exit": 10,
                "rvol_min": 2.0, "trail": True}),
            ("추세 EMA10/30", {"mode": "trend", "ema_fast": 10, "ema_slow": 30}),
            ("눌림목 EMA20/50", {"mode": "pullback", "ema_fast": 20, "ema_slow": 50}),
        ]
        train = {s: c[:int(len(c) * 0.65)] for s, c in data.items()}
        test = {s: c[int(len(c) * 0.65):] for s, c in data.items()}
        ref = train[next(iter(train))]
        rt = test[next(iter(test))]
        print(f"학습 {(ref[-1]['ts'] - ref[0]['ts']) / 1000 / 86400:.0f}일 / "
              f"검증 {(rt[-1]['ts'] - rt[0]['ts']) / 1000 / 86400:.0f}일")
        print("=" * 92)
        print(f"{'조합':<24}{'│ 학습 건수':>10}{'기대값':>9}{'PF':>6}{'  │ 검증 건수':>13}{'기대값':>9}{'PF':>6}")
        print("-" * 92)
        for name, ov in combos:
            p = dict(DEFAULT)
            p.update(ov)
            strn, _ = run_one(train, p)
            ste, _ = run_one(test, p)
            def cell(s):
                return f"{s['n']:>6}{s['exp']:>+9.2f}%{s['pf']:>6.2f}" if s else f"{'0':>6}{'-':>16}"
            print(f"{name:<24}│{cell(strn)}  │{cell(ste)}")
        print("=" * 92)
        print("※ 검증(미래구간)에서도 PF>1·기대값+ 유지되면 국면운이 아닌 추세추종 본연의 엣지.")
        print("※ 단 생존편향(오늘 top-20=과거 승자)은 train/test로도 못 거름 — 기대치는 보수적으로.")
        return

    combos = [
        ("추세 EMA20/50 · ATR손절3 · 추세이탈청산", {"mode": "trend", "ema_fast": 20, "ema_slow": 50}),
        ("추세 EMA10/30 · ATR손절3", {"mode": "trend", "ema_fast": 10, "ema_slow": 30}),
        ("추세 EMA20/50 · ATR손절3 · 트레일", {"mode": "trend", "trail": True}),
        ("추세 EMA20/50 · 목표20%", {"mode": "trend", "target": 0.20}),
        ("돌파 돈치안20/10 · ATR손절3", {"mode": "breakout", "don_n": 20, "don_exit": 10}),
        ("돌파 돈치안20/10 · 트레일", {"mode": "breakout", "don_n": 20, "don_exit": 10, "trail": True}),
        ("돌파 돈치안55/20(터틀) · 트레일", {"mode": "breakout", "don_n": 55, "don_exit": 20, "trail": True}),
        ("눌림목 EMA20/50 · ATR손절3", {"mode": "pullback", "ema_fast": 20, "ema_slow": 50}),
        ("눌림목 EMA20/50 · 트레일", {"mode": "pullback", "trail": True}),
    ]
    print("=" * 86)
    print(f"{'조합':<42}{'건수':>5}{'승률':>7}{'기대값':>9}{'PF':>6}{'누적':>9}{'보유일':>7}")
    print("-" * 86)
    best = None
    for name, ov in combos:
        p = dict(DEFAULT)
        p.update(ov)
        s, _ = run_one(data, p)
        if s:
            print(f"{name:<42}{s['n']:>5}{s['wr']:>6.1f}%{s['exp']:>+8.2f}%"
                  f"{s['pf']:>6.2f}{s['total']:>+8.1f}%{s['days']:>6.0f}일")
            if best is None or s["total"] > best[1]["total"]:
                best = (name, s, p)
        else:
            print(f"{name:<42}{'0':>5}  (진입 없음)")
    print("=" * 86)
    if best:
        print(f"\n▶ 최고 누적: {best[0]}  (PF {best[1]['pf']:.2f} · 평균보유 {best[1]['days']:.0f}일)")
        print("  ── 상세 ──")
        run_one(data, best[2], by_detail=True)
    print("\n※ 표본 단일 기간 — 양수여도 train/test 분리 검증 필요. 실거래 전 페이퍼 포워드테스트.")


if __name__ == "__main__":
    main()
