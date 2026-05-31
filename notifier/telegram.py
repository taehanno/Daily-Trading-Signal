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
