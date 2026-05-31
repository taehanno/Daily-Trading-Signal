# ============================================
# 텔레그램 발송기
# ============================================
"""
Bot API: POST https://api.telegram.org/bot{TOKEN}/sendMessage
- parse_mode=HTML 사용
- DRY_RUN 이면 콘솔에만 출력
"""
import html
import requests


def _esc(s):
    """HTML parse_mode 충돌 방지용 이스케이프 (< > & 등). 구조 태그는 별도로 직접 작성."""
    return html.escape(str(s), quote=False)


def _fmt_price(p):
    if p is None:
        return "-"
    if p >= 100:
        return f"{p:,.0f}원"
    return f"{p:,.4f}원"


def _fmt_change(pct):
    if pct is None:
        return ""
    arrow = "▲" if pct >= 0 else "▼"
    return f"{arrow}{abs(pct):.2f}%"


def build_signal_message(symbol, sig, interval):
    """단건 시그널 알림 메시지(HTML)."""
    lines = [
        f"<b>{sig['label_kr']}</b>  <code>{_esc(symbol)}/KRW</code>",
        f"가격 {_fmt_price(sig['price'])}  {_fmt_change(sig['change_pct'])}  ({interval}봉)",
        f"EMA 5/20/60: {_fmt_price(sig['ema_fast'])} / {_fmt_price(sig['ema_mid'])} / {_fmt_price(sig['ema_slow'])}",
    ]
    # 매수 시그널이면 예상 보유기간 강조
    horizon = sig.get("horizon")
    if horizon:
        lines.append(f"⏳ <b>예상 보유: {_esc(horizon[0])}</b> · {_esc(horizon[1])}")
    # 행동 가이드 — 유지/청산 조건
    pb = sig.get("playbook")
    if pb:
        if pb.get("hold"):
            lines.append(f"✅ <b>유지</b>: {_esc(pb['hold'])}")
        if pb.get("exit"):
            lines.append(f"🚪 <b>청산</b>: {_esc(pb['exit'])}")
    if sig.get("reasons"):
        lines.append("")
        lines.extend(f"• {_esc(r)}" for r in sig["reasons"])
    return "\n".join(lines)


def build_summary_message(results, interval, top=10):
    """일일 요약 메시지(HTML). results: [(symbol, sig)] 스코어 내림차순 정렬됨."""
    from core.signal import BUY_SIDE, SELL_SIDE
    buys = [(s, r) for s, r in results if r["label"] in BUY_SIDE]
    sells = [(s, r) for s, r in results if r["label"] in SELL_SIDE]
    lines = [f"<b>📊 데일리 시그널 요약</b> ({interval}봉 기준)", ""]

    # 라벨 한글에서 이모지 뒤 핵심어만 (예: "🟢 선제 매수 (정배열 임박)" → "선제 매수")
    def _short(label_kr):
        body = label_kr.split(" ", 1)[1] if " " in label_kr else label_kr
        return body.split(" (")[0]

    def _row(s, r):
        h = r.get("horizon")
        tail = f" · {_esc(h[0])}" if h else ""
        return f"  <code>{_esc(s)}</code>  {_esc(_short(r['label_kr']))}  {_fmt_change(r['change_pct'])}{tail}"

    lines.append(f"<b>🟢 매수 후보 {len(buys)}</b>")
    if buys:
        lines.extend(_row(s, r) for s, r in buys[:top])
    else:
        lines.append("  없음")

    lines.append("")
    lines.append(f"<b>🔴 매도 후보 {len(sells)}</b>")
    if sells:
        lines.extend(_row(s, r) for s, r in sells[:top])
    else:
        lines.append("  없음")

    lines.append("")
    lines.append("<i>※ 투자 참고용 시그널이며 투자 책임은 본인에게 있습니다.</i>")
    return "\n".join(lines)


def _short(label_kr):
    """이모지 뒤 핵심어만 (예: "🟢 선제 매수 (정배열 임박)" → "선제 매수")."""
    body = label_kr.split(" ", 1)[1] if " " in label_kr else label_kr
    return body.split(" (")[0]


def build_status_message(results, since, prev_signals, interval, now_str):
    """매시간 전 종목 현황 다이제스트(HTML).

    - results: [(symbol, sig)] 스코어 내림차순
    - since: {symbol: "YYYY-MM-DD HH:MM"} 현재 시그널이 '발생'한 시각
    - prev_signals: 직전 실행의 {symbol: label} (변화 판정용)
    - now_str: 현재 시각 문자열(KST)
    변화가 없어도 항상 1건을 만든다. (각 종목의 발생 시각과 동일 여부 표기)
    """
    from core.signal import BUY_SIDE, SELL_SIDE, LABELS

    def _mark(sym, sig):
        """변화 표식. 신규/방금 변화/동일 중 하나."""
        prev = prev_signals.get(sym)
        if prev is None:
            return "🆕 신규 포착"
        if prev != sig["label"]:
            return f"🔄 방금 변화: {_esc(_short(LABELS.get(prev, prev)))} → {_esc(_short(sig['label_kr']))}"
        s = since.get(sym)
        return f"· 발생 {_esc(s)} 이후 동일" if s else "· 직전과 동일"

    def _row(sym, sig, with_horizon=False):
        h = sig.get("horizon")
        tail = f" · ⏳{_esc(h[0])}" if (with_horizon and h) else ""
        return (f"  <code>{_esc(sym)}</code> {_esc(_short(sig['label_kr']))} "
                f"{_fmt_change(sig['change_pct'])}{tail}  {_mark(sym, sig)}")

    def _buy_block(sym, sig):
        """매수 후보: 헤더 + 보유기간 + 유지/청산 가이드(2~3줄)."""
        out = [(f"  <code>{_esc(sym)}</code> {_esc(_short(sig['label_kr']))} "
                f"{_fmt_change(sig['change_pct'])}  {_mark(sym, sig)}")]
        h = sig.get("horizon")
        if h:
            out.append(f"    ⏳ {_esc(h[0])} · {_esc(h[1])}")
        pb = sig.get("playbook")
        if pb:
            if pb.get("hold"):
                out.append(f"    ✅ 유지: {_esc(pb['hold'])}")
            if pb.get("exit"):
                out.append(f"    🚪 청산: {_esc(pb['exit'])}")
        return "\n".join(out)

    def _sell_block(sym, sig):
        """매도 후보: 헤더 + 행동(보유자 기준)."""
        head = _row(sym, sig)
        pb = sig.get("playbook")
        if pb and pb.get("exit"):
            return head + f"\n    🚪 {_esc(pb['exit'])}"
        return head

    buys = [(s, r) for s, r in results if r["label"] in BUY_SIDE]
    sells = [(s, r) for s, r in results if r["label"] in SELL_SIDE]
    watches = [(s, r) for s, r in results if r["label"] == "WATCH"]
    holds = [(s, r) for s, r in results if r["label"] == "HOLD"]

    n_new = sum(1 for s, _ in results if prev_signals.get(s) is None)
    n_chg = sum(1 for s, r in results
                if prev_signals.get(s) is not None and prev_signals.get(s) != r["label"])
    n_same = len(results) - n_new - n_chg

    lines = [f"<b>📡 시그널 현황</b>  {_esc(now_str)} ({interval}봉)", ""]

    lines.append(f"<b>🟢 매수 후보 {len(buys)}</b>")
    lines.extend(_buy_block(s, r) for s, r in buys) if buys else lines.append("  없음")

    lines.append("")
    lines.append(f"<b>🔴 매도 후보 {len(sells)}</b>")
    lines.extend(_sell_block(s, r) for s, r in sells) if sells else lines.append("  없음")

    if watches:
        lines.append("")
        lines.append(f"<b>👀 관찰 {len(watches)}</b>")
        lines.extend(_row(s, r) for s, r in watches)

    if holds:
        lines.append("")
        lines.append(f"<b>⚪ 관망 {len(holds)}</b>")
        lines.append("  " + ", ".join(f"<code>{_esc(s)}</code>" for s, _ in holds))

    lines.append("")
    if n_new == 0 and n_chg == 0:
        lines.append("<b>이번 시간 변화 없음</b> — 모든 종목 직전과 동일")
    else:
        lines.append(f"<b>변화 요약</b>: 신규 {n_new} · 변화 {n_chg} · 동일 {n_same}")
    if buys or sells:
        lines.append("<i>📖 같은 시그널 유지 = 보유 / 🔴 매도·적극매도로 바뀌면 = 청산</i>")
    lines.append("<i>※ 투자 참고용 시그널이며 투자 책임은 본인에게 있습니다.</i>")
    return "\n".join(lines)


def send(cfg, text: str) -> bool:
    """텔레그램 발송. 성공 여부 반환."""
    if cfg.DRY_RUN:
        print("\n----- [DRY_RUN 메시지] -----")
        # HTML 태그 제거 + 엔티티 복원해서 콘솔 가독성 확보
        import re
        print(html.unescape(re.sub(r"<[^>]+>", "", text)))
        print("----------------------------\n")
        return True

    url = f"https://api.telegram.org/bot{cfg.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": cfg.TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=15)
        if r.status_code != 200:
            print(f"[telegram] 발송 실패 {r.status_code}: {r.text[:200]}")
            return False
        return True
    except requests.RequestException as e:
        print(f"[telegram] 요청 오류: {e}")
        return False
