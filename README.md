# Daily Trading Signal — Bithumb 시그널 텔레그램 봇

Bithumb 공개 API로 코인을 분석해 **매수/매도 포지션 시그널**을 계산하고,
**내 텔레그램으로 실시간 알림 + 일일 요약**을 보내는 봇입니다.
Render(클라우드)에서 24시간 상시 실행됩니다.

---

## 1. 동작 개요

```
[Bithumb Public API] → [지표 계산] → [복합 스코어] → [포지션 판정] → [텔레그램 발송]
   티커/캔들           RSI·MACD·MA      합산 점수      BUY/SELL/HOLD     실시간+일일요약
```

- **분석 대상**: `COINS`에 지정한 코인, 또는 24H 거래대금 상위 `TOP_N`개 자동 선정(스테이블코인 제외)
- **분석 주기**: `CHECK_INTERVAL_MIN`분마다 (기본 60분)
- **알림 정책**: `on_change`(시그널이 바뀔 때만 — 스팸 방지) / `always`
- **일일 요약**: 매일 `DAILY_SUMMARY_HOUR`시(KST)에 매수·매도 후보 종합 1회

---

## 2. 시그널 로직 (복합 스코어)

여러 지표를 점수화해 합산합니다. **+면 매수 우위, −면 매도 우위.**

| 지표 | 매수(+) 조건 | 매도(−) 조건 |
|------|------------|------------|
| **RSI(14)** | ≤30 과매도 `+2`, ≤40 저점권 `+1` | ≥70 과매수 `−2`, ≥60 고점권 `−1` |
| **이동평균(7/25)** | 골든크로스 `+2`, 정배열 `+1` | 데드크로스 `−2`, 역배열 `−1` |
| **MACD(12/26/9)** | 상향교차 `+2`, 히스토 양 `+1` | 하향교차 `−2`, 히스토 음 `−1` |
| **볼린저밴드(20,2σ)** | 하단 터치 `+1` | 상단 터치 `−1` |
| **거래량 급증** | 상승 동반 `+1` | 하락 동반 `−1` |

**판정 기준**

| 합산 스코어 | 포지션 |
|-----------|--------|
| ≥ +4 | 🟢 적극 매수 (STRONG_BUY) |
| +2 ~ +3 | 🟢 매수 (BUY) |
| −1 ~ +1 | ⚪ 관망 (HOLD) |
| −2 ~ −3 | 🔴 매도 (SELL) |
| ≤ −4 | 🔴 적극 매도 (STRONG_SELL) |

> 모든 임계값은 환경변수로 조정 가능 (`RSI_PERIOD`, `MA_SHORT/LONG`, `BB_PERIOD` 등).

---

## 3. 프로젝트 구조

```
Daily-Trading-Signal/
├─ main.py              # 오케스트레이터(분석 루프 + 스케줄)
├─ config.py            # 환경변수 기반 설정
├─ exchanges/
│  └─ bithumb.py        # Bithumb 공개 API 클라이언트
├─ core/
│  ├─ indicators.py     # RSI/MACD/MA/볼린저/거래량 (순수 파이썬)
│  └─ signal.py         # 복합 스코어 → 포지션 판정
├─ notifier/
│  └─ telegram.py       # 텔레그램 발송 + 메시지 포맷
├─ requirements.txt
├─ render.yaml          # Render 배포(백그라운드 워커)
└─ .env.example
```

---

## 4. 텔레그램 봇/채팅 ID 준비

1. 텔레그램에서 **@BotFather** 검색 → `/newbot` → 봇 이름 지정 → **봇 토큰** 발급
   - 예: `123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxx`
2. 만든 봇과 **대화 시작**(아무 메시지나 전송)
3. **내 chat_id 확인**: 브라우저에서
   `https://api.telegram.org/bot<봇토큰>/getUpdates`
   → 응답의 `"chat":{"id": ...}` 숫자가 `TELEGRAM_CHAT_ID`

---

## 5. 로컬 테스트

```bash
pip install -r requirements.txt

# (1) 텔레그램 없이 콘솔로만 확인 — 발송 안 함
DRY_RUN=true ONESHOT=true python main.py

# (2) 실제 내 텔레그램으로 1회 발송
TELEGRAM_BOT_TOKEN=토큰 TELEGRAM_CHAT_ID=아이디 ONESHOT=true python main.py
```

> Windows PowerShell은 `$env:DRY_RUN="true"; python main.py` 형식.
> Git Bash 권장.

---

## 6. Render 배포 (24시간 상시 실행)

1. 이 폴더를 **자체 GitHub repo**로 푸시 (홈 디렉토리 mega-repo와 분리)
2. [Render](https://render.com) → **New → Blueprint** → 해당 repo 선택
3. `render.yaml`이 자동 인식됨 → **Worker** 서비스 생성
4. 대시보드 **Environment**에 민감정보 입력:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
5. Deploy → 로그에서 분석/발송 확인

> ⚠️ Render **free 플랜은 worker 미지원** → `render.yaml`은 `starter`(유료, 월 $7)로 설정.
> 무료로 쓰려면 [cron-job.org](https://cron-job.org) 등 외부 스케줄러로 `ONESHOT=true` 1회 실행을 주기 호출하는 방식도 가능.

---

## 7. 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `TELEGRAM_BOT_TOKEN` | (필수) | BotFather 봇 토큰 |
| `TELEGRAM_CHAT_ID` | (필수) | 내 chat id |
| `COINS` | (없음) | 분석할 코인 CSV. 비우면 자동 상위 선정 |
| `TOP_N` | `15` | 자동 선정 시 상위 N개 |
| `EXCLUDE` | 스테이블코인 | 자동 선정 제외 심볼 |
| `CANDLE_INTERVAL` | `1h` | 1m/3m/5m/10m/30m/1h/6h/12h/24h |
| `CHECK_INTERVAL_MIN` | `60` | 분석 주기(분) |
| `DAILY_SUMMARY_HOUR` | `9` | 일일 요약 시각(KST). `-1`이면 끔 |
| `ALERT_MODE` | `on_change` | `on_change` / `always` |
| `ALERT_ON_HOLD` | `false` | 관망 시그널도 알림할지 |
| `DRY_RUN` | `false` | true면 콘솔 출력(발송 안 함) |
| `ONESHOT` | `false` | true면 1회 실행 후 종료 |

---

## 8. API 명세 (사용 중인 Bithumb Public API)

```
### 전체 티커
- Method: GET
- URL: https://api.bithumb.com/public/ticker/ALL_KRW
- 인증: 불필요
- Response: { status:"0000", data:{ BTC:{ acc_trade_value_24H, ... }, ... } }

### 캔들
- Method: GET
- URL: https://api.bithumb.com/public/candlestick/{SYMBOL}_KRW/{interval}
- Response: { status:"0000", data:[ [ts, open, close, high, low, volume], ... ] }
- 주의: row 순서는 [시각, 시가, 종가, 고가, 저가, 거래량] (OHLC 아님)

### 텔레그램 발송
- Method: POST
- URL: https://api.telegram.org/bot{TOKEN}/sendMessage
- Body: { chat_id, text, parse_mode:"HTML" }
```

---

## ⚠️ 면책

이 봇이 생성하는 시그널은 **투자 참고용 보조 지표**이며, 매매 권유가 아닙니다.
모든 투자 판단과 책임은 사용자 본인에게 있습니다.
