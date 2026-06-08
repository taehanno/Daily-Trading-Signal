# ============================================
# 백테스트 — 단타 점화 전략 승률/손익 검증 (walk-forward)
# ============================================
"""
배포된 signal.analyze() 엔진을 5분봉 과거 데이터에 그대로 재생한다.

룩어헤드 방지:
  · 시그널은 '봉 마감 후' 확정 → 진입은 '다음 봉 시가'에 체결(현실적).
  · analyze()는 마지막 봉을 미완성으로 보고 직전 봉으로 평가하므로,
    candles[:i+2] 를 넘기면 평가봉 = bar i (방금 마감) 가 된다.

정산(보수적):
  · 같은 봉에서 손절가·목표가를 동시에 터치하면 손절 우선(승률 과대평가 방지).
  · 진입에 슬리피지, 청산에 왕복 수수료 반영.
  · 당일 단타 → 날짜(KST)가 바뀌면 시가에 강제 청산. 시간 손절(MAX_HOLD)도 적용.
  · 한 종목당 동시 1포지션(청산 전 신규 진입 없음).

청산 우선순위(보유 중 매 봉): 손절 → 목표 → 엔진 EXIT_SCALP(VWAP이탈/과열/대량음봉) → 날짜변경 → 시간손절

실행:
  python scripts/backtest.py
  BT_FEE=0.001 BT_SLIP=0.0005 BT_MAX_HOLD=24 TOP_N=20 python scripts/backtest.py
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
from core import signal as sig_engine

KST = timezone(timedelta(hours=9))

# 엔진에 넘길 트레일링 윈도(속도). 지표는 ~60봉 + 당일세션(≤288봉)이면 충분.
WINDOW = 360
FEE = float(os.environ.get("BT_FEE", 0.001))        # 왕복 수수료(0.1% 가정)
SLIP = float(os.environ.get("BT_SLIP", 0.0005))     # 진입 슬리피지(0.05%)
MAX_HOLD = int(os.environ.get("BT_MAX_HOLD", 24))   # 시간 손절(봉 수, 24=2시간)


def _kst_date(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, KST).date()


def _kst_hour(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, KST).hour


def simulate_symbol(sym, cfg, candles):
    """한 종목 walk-forward 시뮬레이션 → 체결된 트레이드 리스트."""
    trades = []
    n = len(candles)
    need = max(cfg.EMA_SLOW, cfg.RVOL_PERIOD + 1,
               cfg.BREAKOUT_LOOKBACK + 1, cfg.RSI_PERIOD + 1) + 4
    i = need
    while i < n - 1:
        lo = max(0, i + 2 - WINDOW)
        win = candles[lo:i + 2]               # 평가봉 = win[-2] = candles[i]
        if len(win) < need:
            i += 1
            continue
        sig = sig_engine.analyze(win, cfg)
        if not sig or sig["label"] != "BUY_IGNITION":
            i += 1
            continue

        entry_idx = i + 1                      # 다음 봉 시가 진입(룩어헤드 방지)
        if entry_idx >= n:
            break
        entry = candles[entry_idx]["open"] * (1 + SLIP)
        stop = sig.get("stop")
        target = sig.get("target")            # 엔진이 산정한 목표(VWAP 복귀 등) 그대로 사용
        if stop is None or stop >= entry or target is None or target <= entry:
            i += 1
            continue
        entry_day = _kst_date(candles[entry_idx]["ts"])

        exit_price = exit_idx = reason = None
        for j in range(entry_idx, min(n, entry_idx + MAX_HOLD + 1)):
            bar = candles[j]
            if bar["low"] <= stop:             # 손절 우선(보수적)
                exit_price, exit_idx, reason = stop, j, "stop"
                break
            if bar["high"] >= target:
                exit_price, exit_idx, reason = target, j, "target"
                break
            if _kst_date(bar["ts"]) != entry_day:   # 당일 단타 — 날짜 변경 시 청산
                exit_price, exit_idx, reason = bar["open"], j, "eod"
                break
            # 엔진 청산 시그널(보유봉 마감 기준)
            wlo = max(0, j + 2 - WINDOW)
            sj = sig_engine.analyze(candles[wlo:j + 2], cfg)
            if sj and sj["label"] == "EXIT_SCALP" and j > entry_idx:
                exit_price, exit_idx, reason = bar["close"], j, "engine_exit"
                break
        if exit_price is None:                 # 시간 손절
            exit_idx = min(n - 1, entry_idx + MAX_HOLD)
            exit_price, reason = candles[exit_idx]["close"], "time"

        gross = (exit_price - entry) / entry
        net = gross - FEE
        trades.append({
            "sym": sym,
            "entry_ts": candles[entry_idx]["ts"],
            "entry_hour": _kst_hour(candles[entry_idx]["ts"]),
            "hold_bars": exit_idx - entry_idx,
            "gross": gross,
            "net": net,
            "reason": reason,
            "win": net > 0,
        })
        i = exit_idx + 1                       # 청산 후 재개(중첩 없음)
    return trades


def _stats(trades):
    if not trades:
        return None
    n = len(trades)
    wins = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]
    win_rate = len(wins) / n * 100
    avg = sum(t["net"] for t in trades) / n
    avg_win = sum(t["net"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["net"] for t in losses) / len(losses) if losses else 0
    gross_profit = sum(t["net"] for t in wins)
    gross_loss = -sum(t["net"] for t in losses)
    pf = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    # 비복리 누적 수익(매 트레이드 동일 비중 가정)
    total = sum(t["net"] for t in trades) * 100
    avg_hold = sum(t["hold_bars"] for t in trades) / n
    return {
        "n": n, "win_rate": win_rate, "avg": avg * 100,
        "avg_win": avg_win * 100, "avg_loss": avg_loss * 100,
        "expectancy": avg * 100, "pf": pf, "total": total, "avg_hold": avg_hold,
    }


def _fetch_all(cfg, targets):
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


def run_sweep(cfg, data):
    """데이터 1회 수신 후 파라미터 조합별 전체 성능 비교(과적합 주의)."""
    global FEE, SLIP, MAX_HOLD
    # (이름, {설정 override})
    combos = [
        ("기본(목표2.5%/손절 봉저점)", {}),
        ("목표1.0%·손절0.6%", {"TARGET_PCT": 0.010, "STOP_PCT": 0.006}),
        ("목표1.5%·손절1.0%", {"TARGET_PCT": 0.015, "STOP_PCT": 0.010}),
        ("목표2.0%·손절1.2%", {"TARGET_PCT": 0.020, "STOP_PCT": 0.012}),
        ("목표2.5%·손절ATR1.5", {"TARGET_PCT": 0.025, "STOP_ATR_MULT": 1.5}),
        ("목표1.5%·손절ATR1.0·RVOL3.5", {"TARGET_PCT": 0.015, "STOP_ATR_MULT": 1.0, "RVOL_TRIGGER": 3.5}),
        ("목표1.2%·손절0.8%·RVOL4.0·RSI55~68", {"TARGET_PCT": 0.012, "STOP_PCT": 0.008,
            "RVOL_TRIGGER": 4.0, "RSI_BUY_MIN": 55.0, "RSI_BUY_MAX": 68.0}),
        ("목표3.0%·손절1.5%·과열2%", {"TARGET_PCT": 0.030, "STOP_PCT": 0.015, "MAX_EXT_VWAP": 0.02}),
    ]
    base = {k: getattr(cfg, k) for k in
            ("TARGET_PCT", "STOP_PCT", "STOP_ATR_MULT", "RVOL_TRIGGER",
             "RSI_BUY_MIN", "RSI_BUY_MAX", "MAX_EXT_VWAP")}
    print("=" * 78)
    print(f"{'조합':<34}{'건수':>5}{'승률':>8}{'기대값':>9}{'PF':>6}{'누적':>9}")
    print("-" * 78)
    for name, ov in combos:
        for k, v in base.items():       # 리셋
            setattr(cfg, k, v)
        for k, v in ov.items():         # 적용
            setattr(cfg, k, v)
        trades = []
        for sym, c in data.items():
            trades.extend(simulate_symbol(sym, cfg, c))
        s = _stats(trades)
        if not s:
            print(f"{name:<34}{'0':>5}")
            continue
        print(f"{name:<34}{s['n']:>5}{s['win_rate']:>7.1f}%{s['expectancy']:>+8.3f}%"
              f"{s['pf']:>6.2f}{s['total']:>+8.1f}%")
    for k, v in base.items():           # 원복
        setattr(cfg, k, v)
    print("=" * 78)
    print("※ 10일 단일 표본 기준 — 양수가 나와도 과적합 가능성. 실거래 전 추가 검증 필수.")


def main():
    cfg = Config
    targets = cfg.COINS or bithumb.top_symbols_by_volume(cfg.QUOTE, cfg.TOP_N)
    if os.environ.get("BT_SWEEP") == "1":
        print(f"데이터 수신 중… (상위 {len(targets)}개)")
        data = _fetch_all(cfg, targets)
        print(f"수신 완료: {len(data)}개 종목")
        run_sweep(cfg, data)
        return
    print("=" * 60)
    print("백테스트 — 단타 점화 전략 (5분봉)")
    print(f"대상 {len(targets)}개 · 수수료(왕복) {FEE * 100:.2f}% · 슬리피지 {SLIP * 100:.3f}% "
          f"· 시간손절 {MAX_HOLD}봉")
    print(f"진입조건: RVOL≥{cfg.RVOL_TRIGGER} · VWAP돌파 · {cfg.BREAKOUT_LOOKBACK}봉고점 · "
          f"EMA{cfg.EMA_FAST}>{cfg.EMA_SLOW} · RSI {cfg.RSI_BUY_MIN:.0f}~{cfg.RSI_BUY_MAX:.0f} · "
          f"VWAP과열≤{cfg.MAX_EXT_VWAP * 100:.0f}%")
    print(f"청산: 목표+{cfg.TARGET_PCT * 100:.1f}% / 손절(봉저점·VWAP) / 엔진EXIT / 당일마감")
    print("=" * 60)

    all_trades = []
    span_days = None
    for sym in targets:
        try:
            candles = bithumb.get_candles(sym, cfg.QUOTE, cfg.CANDLE_INTERVAL)
        except bithumb.BithumbError as e:
            print(f"  {sym}: 조회 실패 {e}")
            continue
        if len(candles) < 100:
            continue
        if span_days is None:
            span_days = (candles[-1]["ts"] - candles[0]["ts"]) / 1000 / 86400
        tr = simulate_symbol(sym, cfg, candles)
        all_trades.extend(tr)
        s = _stats(tr)
        if s:
            print(f"  {sym:<8} 트레이드 {s['n']:>3} · 승률 {s['win_rate']:>5.1f}% · "
                  f"평균 {s['avg']:+.2f}% · 누적 {s['total']:+.1f}% · PF {s['pf']:.2f}")
        else:
            print(f"  {sym:<8} 진입 0건")
        bithumb.polite_sleep(cfg.REQUEST_SLEEP)

    print("=" * 60)
    s = _stats(all_trades)
    if not s:
        print("체결된 트레이드가 없습니다(진입 조건 미충족).")
        return
    print(f"📊 전체 결과  (기간 약 {span_days:.1f}일)")
    print(f"  총 트레이드 : {s['n']}")
    print(f"  승률        : {s['win_rate']:.1f}%  (승 {sum(t['win'] for t in all_trades)} / "
          f"패 {s['n'] - sum(t['win'] for t in all_trades)})")
    print(f"  기대값/건   : {s['expectancy']:+.3f}%  (수수료·슬리피지 반영 후)")
    print(f"  평균 수익(승): {s['avg_win']:+.2f}%   평균 손실(패): {s['avg_loss']:+.2f}%")
    print(f"  손익비(PF)  : {s['pf']:.2f}  (1.0 초과면 +기대)")
    print(f"  누적(비복리): {s['total']:+.1f}%   평균 보유 {s['avg_hold']:.1f}봉(~{s['avg_hold'] * 5:.0f}분)")

    # 청산 사유 분포
    reasons = {}
    for t in all_trades:
        reasons.setdefault(t["reason"], []).append(t)
    print("  ── 청산 사유별 ──")
    label = {"target": "목표달성", "stop": "손절", "engine_exit": "엔진청산",
             "eod": "당일마감", "time": "시간손절"}
    for r, ts in sorted(reasons.items(), key=lambda x: -len(x[1])):
        wr = sum(t["win"] for t in ts) / len(ts) * 100
        avg = sum(t["net"] for t in ts) / len(ts) * 100
        print(f"     {label.get(r, r):<8} {len(ts):>3}건 ({len(ts) / s['n'] * 100:4.1f}%) · "
              f"승률 {wr:5.1f}% · 평균 {avg:+.2f}%")

    # 시간대별(거래 집중 시간대 검증)
    print("  ── 진입 시간대별(KST) ──")
    by_hour = {}
    for t in all_trades:
        by_hour.setdefault(t["entry_hour"], []).append(t)
    for h in sorted(by_hour):
        ts = by_hour[h]
        wr = sum(t["win"] for t in ts) / len(ts) * 100
        avg = sum(t["net"] for t in ts) / len(ts) * 100
        key = " 🔥" if h in cfg.KEY_HOURS else ""
        print(f"     {h:02d}시{key:<2} {len(ts):>3}건 · 승률 {wr:5.1f}% · 평균 {avg:+.2f}%")

    print("=" * 60)
    print("※ 한계: 5분봉 과거가 약 10일치뿐이라 표본이 작고, 단일 시장국면만 반영.")
    print("※ 봉내 체결순서는 손절 우선(보수적) 가정 — 실제 승률은 이보다 높을 수 있음.")


if __name__ == "__main__":
    main()
