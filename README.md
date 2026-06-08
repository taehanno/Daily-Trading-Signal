# Daily Trading Signal — Bithumb 시그널 텔레그램 봇

Bithumb 공개 API로 코인을 분석해 **매수/매도 포지션 시그널**을 계산하고,
**내 텔레그램으로 실시간 알림 + 일일 요약**을 보내는 봇입니다.
Render(클라우드)에서 24시간 상시 실행됩니다.

---

## 1. 동작 개요

```
[Bithumb Public API] → [지표 계산] → [돌파 판정] → [텔레그램 발송]
   일봉 OHLCV          돈치안·RVOL·EMA·ATR   진입/청산      이벤트 알림
```

- **분석 대상**: `COINS`에 지정한 코인, 또는 24H 거래대금 상위 `TOP_N`개 자동 선정
- **분석 주기**: 하루 1회면 충분(확정 일봉은 하루 한 번만 바뀜). 자주 돌려도 페이퍼 로직 멱등.
- **알림 정책**: `on_change`(시그널이 바뀔 때만 — 스팸 방지) / `always`
- **타임프레임**: 일봉(`CANDLE_INTERVAL=24h`). 마지막 **확정 봉**으로 평가(형성 중 봉 제외)

---

## 2. 시그널 로직 (일봉 스윙 — 돈치안 돌파 + 거래량 급증)

핵심 아이디어: **5분·1시간 단타는 수수료(왕복 0.08%)에 엣지가 먹혀 전부 본전~마이너스**로 검증됨.
시간축을 **일봉**으로 올리면 한 번의 추세를 며칠~몇주 먹으므로 수수료가 무의미해지고, **추세추종 본연의
엣지(손실 짧게·수익 길게 = 양의 왜도)** 가 살아난다. 신고가 돌파(돈치안)에 **거래량 급증**이 동반될 때만
진입한다 — 거래량 폭발은 *지금 수급/뉴스가 들어오는 흔적*이라 가짜 돌파를 거르고 신호 수를 줄인다.

판정은 우선순위대로 먼저 맞는 것을 채택한다.

| 시그널 | 조건 | 의미 |
|--------|------|------|
| 🔴 **청산 (EXIT_SCALP)** | 종가 < 직전 `SWING_DON_EXIT`일 저점(청산선) | 추세 전환 — 보유자 매도 |
| 📈 **스윙 매수 (BUY_IGNITION)** ⭐ | 아래 3개 동시 충족 | 돌파+거래량 진입 |
| 👀 **관찰 (WATCH_VOL)** | 돌파했으나 거래량 부족 / 돌파 임박 | 거래량 확인 대기 (기본 알림 off, `ALERT_ON_WATCH=true`) |
| ⚪ **관망 (HOLD)** | 그 외 | — |

**스윙 매수(BUY_IGNITION) 진입 조건 — 전부 동시 충족:**

| 조건 | 기준 | 역할 |
|------|------|------|
| 종가 > 직전 `SWING_DON_N`일 고점 | 기본 20일 | **신고가 돌파** — 추세 점화 |
| RVOL ≥ `SWING_RVOL_MIN` | 기본 2.0배 | **거래량 급증** — 지금 수급/뉴스(돌파 진위·선별) |
| EMA`FAST` > EMA`SLOW` | 기본 20/50 | 상위 추세 상방 |

- **손절**: 진입가 − `SWING_ATR_STOP`×ATR (기본 3배).
- **청산선(팔아야 하는 가격)**: 직전 `SWING_DON_EXIT`일 저점(기본 10일) — 매일 갱신, 일봉 종가가 이 아래로 마감하면 매도. **고정 목표는 두지 않는다**(승자를 일찍 자르면 엣지가 죽음 — 추세 끝까지 보유).
- 청산은 손절/엔진청산(추세전환)/시간손절(`PAPER_MAX_HOLD_DAYS`, 기본 60일)을 페이퍼·백테스트 정산기가 처리.

> ⚠️ 스윙이라 보유 기준은 **2~4주(평균 ~23일)**. 승률은 낮아도(≈36%) 소수의 큰 추세가 수익을 만든다 — **신호를 골라 받지 말 것**.

### 2-1. 백테스트 결과 & 페이퍼 트레이딩 (중요)

약 1050일 일봉 walk-forward(`scripts/backtest_swing.py`), **train/test 시간 분리** 검증:
**돈치안20 돌파 + RVOL≥2.0**가 학습·검증(미래구간) **둘 다 PF 3.4~4.0**(out-of-sample 유지).
거래량 필터가 거래를 1/3 줄이면서 수익의 84%를 지켜 PF를 끌어올렸다(`BT_VOL=1`). 단타(5분·1시간)는
`backtest.py`/`backtest_meanrev.py`/`backtest_pullback.py`에서 전부 본전~마이너스였다.

⚠️ **한계**: ① **생존편향**(분석 대상이 *오늘* top-20 = 과거 승자) → 실제론 더 낮음 ② 단일 강세장 비중.
→ 그래서 **실돈 자동매매 대신 페이퍼 트레이딩(`PAPER_TRADING=true`)** 으로 **진짜 out-of-sample(실시간)**
포워드테스트한다. `BUY_IGNITION`마다 가상 진입을 열고 손절/추세전환/시간손절로 닫아 **누적 성적표(승률·
기대값·PF)** 를 `state.json`에 쌓는다. 실시간에서도 +EV가 유지되면 그때 소액 실거래를 재평가.
모든 알림에 `ℹ️ 정보용 — 실제 주문 아님`을 명시한다.

---

## 3. 프로젝트 구조

```
Daily-Trading-Signal/
├─ main.py              # 오케스트레이터(분석 루프 + 스케줄)
├─ config.py            # 환경변수 기반 설정
├─ exchanges/
│  └─ bithumb.py        # Bithumb 공개 API 클라이언트
├─ core/
│  ├─ indicators.py     # EMA/RSI/RVOL/VWAP/ATR 등 (순수 파이썬)
│  └─ signal.py         # 일봉 스윙 엔진(돈치안 돌파+거래량) → 진입/청산 + 손절·청산선
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
| `TOP_N` | `20` | 자동 선정 시 상위 N개 |
| `EXCLUDE` | (없음) | 자동 선정 제외 심볼 |
| `CANDLE_INTERVAL` | `5m` | 단타 스캘핑 기본. 1m/3m/5m/10m/30m/1h/... |
| `EMA_FAST/SLOW` | `9/21` | 단기 모멘텀 EMA 기간 |
| `RVOL_PERIOD` | `20` | 상대거래량 평균 산정 봉 수 |
| `RVOL_TRIGGER` | `2.5` | 진입 거래량 배수(주 트리거) |
| `RVOL_WATCH` | `1.8` | 관찰(점화 대기) 배수 |
| `RVOL_MIN` | `2.0` | 시간대 완화 하한 |
| `BREAKOUT_LOOKBACK` | `20` | 직전 N봉 고점 돌파 |
| `MAX_EXT_VWAP` | `0.04` | VWAP 대비 과열 한도(+4%) — 추격 금지 |
| `RSI_PERIOD` | `14` | RSI 기간 |
| `RSI_BUY_MIN/MAX` | `50/72` | 진입 허용 RSI 밴드 |
| `RSI_OVERHEAT` | `80` | 청산(블로우오프) 기준 |
| `TARGET_PCT` | `0.025` | 목표 수익(+2.5%) |
| `KEY_HOURS` | `8,9,10,20,21,22` | 거래 집중 시간대(KST) — RVOL 완화 |
| `KEY_HOUR_RELAX` | `0.5` | 집중 시간대 트리거 인하폭 |
| `CHECK_INTERVAL_MIN` | `5` | 분석 주기(분) — 로컬 루프용 |
| `DAILY_SUMMARY_HOUR` | `-1` | 일일 요약 시각(KST). `-1`이면 끔 |
| `ALERT_MODE` | `on_change` | `on_change` / `always` |
| `ALERT_ON_WATCH` | `false` | 관찰(점화 대기) 시그널도 알림할지 |
| `PAPER_TRADING` | `true` | 가상매매 기록 모드(실돈 X). 진입/청산+누적 성적표 |
| `PAPER_FEE` | `0.001` | 페이퍼 왕복 수수료 가정(0.1%) |
| `PAPER_MAX_HOLD_BARS` | `24` | 페이퍼 시간손절(봉, 24=2시간) |
| `PAPER_SUMMARY_HOUR` | `9` | 페이퍼 일일 요약 발송 시각(KST). `-1`이면 끔 |
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
