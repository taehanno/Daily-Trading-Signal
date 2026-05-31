# CLAUDE.md — 프로젝트 개발 정책 (Product Manager 기준)

> 노태한 (InfiniteBlock PM/BD) 작업 표준
> 모든 신규 프로젝트 루트에 `CLAUDE.md` 또는 `.claude/CLAUDE.md`로 배치
> Claude Code가 이 파일을 자동으로 컨텍스트에 로드함

---

## 0. 역할 및 산출물 정의

- **나는 Product Manager**다. 개발자/디자이너에게 **전달용 데모**를 만드는 것이 목적.
- 산출물은 **GitHub Pages로 즉시 배포 가능한 순수 HTML/CSS/JS 단일 파일** 형태.
- React는 **CDN 방식 (esm.sh / unpkg)** 으로만 사용. 빌드 단계 없음.
- 최종 결과물은 **개발자가 보고 그대로 옮길 수 있을 만큼 구체적**이어야 한다.
- 데모 동작 + API 명세 확인까지 포함해서 작업한다.

---

## 1. 기술 스택 제약 (Strict)

### 필수
- **단일 HTML 파일** (`index.html`) 안에 HTML/CSS/JS 모두 포함
- 외부 의존성은 CDN만 허용 (npm install 금지)
- GitHub Pages 정적 배포 가능해야 함 (서버 사이드 로직 금지)
- 모바일 반응형 기본 포함
  - `@media (max-width: 767px)` → 모바일
  - `@media (max-width: 1024px)` → 태블릿
  - 폰트/간격/레이아웃 모바일 최적화 필수

### 금지
- Node.js 빌드 도구 (Vite, Webpack, Next.js 등)
- 백엔드 의존 기능 (실제 DB 연결, 서버 세션 등)
- 외부 인증이 필요한 API (데모는 mock 데이터로)

---

## 2. 화면기획서 필수 포함 항목 (모든 화면에 적용)

화면 하나 만들 때 아래 항목이 **빠지면 안 된다.** 누락 시 셀프 체크 후 보완.

### 인터랙션
- [ ] 모든 버튼의 **클릭 시 동작 및 결과 상태** 명확히 정의
- [ ] **Toast Popup / Alert / Confirm** 문구 및 노출 조건 명시
- [ ] **상세조회 Popup/Modal** 화면 및 데이터 출력 정의

### 다운로드/파일
- [ ] **CSV 다운로드** — 실제 다운로드 가능 형태로 구현 (Blob + URL.createObjectURL)
- [ ] **PDF 다운로드** — 실제 파일 생성 및 다운로드 가능 (jsPDF 등 CDN 활용)

### 검색/조회
- [ ] **날짜 기간조회 필터** (Start Date / End Date) 기본 제공
- [ ] **페이지네이션, 정렬(Sort), 검색조건 유지 여부** 명시
- [ ] 필터 초기화 버튼 포함

### CRUD 상태
- [ ] **조회/등록/수정/삭제 성공·실패 예외 케이스** 포함
- [ ] **로딩 상태** (Spinner / Skeleton) 정의
- [ ] **빈 데이터 화면** (Empty State) 정의
- [ ] 에러 상태 (네트워크 실패, 권한 없음 등)

### API 명세
- [ ] **API 연동 기준** (Request/Response 스펙) 주석 또는 별도 섹션으로 명시
- [ ] **Validation 규칙** 포함 (필수값, 형식, 길이 제한)
- [ ] HTTP 메서드, 엔드포인트, 헤더, 인증 방식

---

## 3. 디자인 시스템 (Strict Spacing & Alignment)

### 디자인 타겟
**Linear / Stripe / Notion / Vercel / Toss 수준**
Desktop SaaS UI. Airy, structured, premium. Cramped 금지.

### 색상 (기본값 — 프로젝트별 조정 가능)
```css
:root {
  /* Neutral */
  --bg: #FFFFFF;
  --bg-subtle: #FAFAFA;
  --border: #E5E5E5;
  --border-strong: #D4D4D4;
  --text-primary: #0A0A0A;
  --text-secondary: #525252;
  --text-tertiary: #A3A3A3;

  /* Accent (InfiniteBlock 톤 호환) */
  --accent: #7B7FF6;
  --accent-hover: #6366F1;
  --accent-subtle: #EEF0FE;

  /* Semantic */
  --success: #10B981;
  --warning: #F59E0B;
  --danger: #EF4444;
  --info: #3B82F6;
}
```

### 간격 스케일 (Strict 4 / 8 / 12 / 16 / 24 / 32 / 48)
**임의의 px 값 사용 금지.** 위 스케일 외 값을 쓰려면 이유를 주석으로 명시.

```css
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-6: 24px;
--space-8: 32px;
--space-12: 48px;
```

### 타이포그래피
- Body: `'Pretendard', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif`
- Korean: Pretendard 우선
- Mono: `'JetBrains Mono', 'D2Coding', monospace`
- Line height: 본문 1.5, 헤딩 1.2~1.3

### 버튼 규칙 (가장 자주 어기는 부분)

```css
.btn {
  /* 좌우 여백 넉넉하게 */
  padding: 10px 20px;        /* 작은 버튼: 8px 16px, 큰 버튼: 12px 24px */
  min-width: 80px;           /* 찌그러짐 방지 */
  min-height: 36px;          /* 최소 클릭 영역 */
  display: inline-flex;
  align-items: center;       /* 수직 중앙 정렬 */
  justify-content: center;
  gap: 8px;                  /* 아이콘과 텍스트 간격 */
  white-space: nowrap;
}

/* Modal 내부 버튼은 더 여유롭게 */
.modal .btn {
  padding: 12px 24px;
  min-width: 100px;
  min-height: 40px;
}

/* Table action 버튼은 compact하지만 답답하지 않게 */
.table-action .btn {
  padding: 6px 12px;
  min-height: 30px;
}
```

### 정렬 (Optical Alignment 포함)
- 카드/메뉴/모달의 **좌우 padding 일관** (보통 24px)
- 메뉴 아이템 **좌측 정렬 동일하게** (아이콘 가운데, 텍스트 baseline 맞춤)
- 모든 버튼 내부 콘텐츠 **vertically center**
- 수학적 정렬이 아닌 **optical alignment** (시각적으로 보기에 맞는가)
- 섹션 간 간격은 일정한 리듬 유지 (예: 모든 섹션 사이 32px)

### Whitespace Hierarchy
```
Title → Content: 16px or 24px
Content → Actions: 24px
Section → Section: 32px or 48px
Card 내부 padding: 24px
Modal 내부 padding: 32px
```

---

## 4. 컴포넌트 표준

### Toast
- 우상단 고정, 자동 3초 후 사라짐
- 성공: 초록 / 실패: 빨강 / 정보: 파랑
- 메시지는 한 줄, 18자 이내 권장

### Modal
- 배경 오버레이 `rgba(0,0,0,0.5)`
- ESC 키, 배경 클릭, X 버튼 모두 닫기 가능
- 닫기 전 변경사항 있으면 Confirm

### Table
- 정렬 가능한 컬럼은 헤더에 화살표 아이콘
- 행 hover 시 배경 변화
- 빈 데이터: 일러스트 + 안내 문구 + CTA

### Form
- Label 위, Input 아래 구조
- Required는 `*` 빨강
- Validation 에러는 Input 하단 빨강 텍스트
- Disabled / Loading 상태 명확히 구분

### Date Picker (기간조회)
- Start Date / End Date 두 개 분리
- 빠른 선택 버튼 (오늘 / 7일 / 30일 / 90일)
- End < Start 방지

---

## 5. API 명세 작성 규칙

각 화면 최상단 주석 또는 별도 `API.md`에 아래 형식으로 기재.

```
## [화면명] - [기능]

### Request
- Method: GET / POST / PUT / DELETE
- URL: /api/v1/resource
- Headers:
  - Authorization: Bearer {token}
  - Content-Type: application/json
- Query / Body:
  - field1 (string, required): 설명
  - field2 (number, optional): 설명

### Response (Success)
{
  "code": 200,
  "data": { ... }
}

### Response (Error)
- 400: Validation 실패
- 401: 인증 실패
- 403: 권한 없음
- 404: 리소스 없음
- 500: 서버 오류

### Validation
- field1: 필수, 1~50자
- field2: 0 이상의 정수
```

---

## 6. 작업 진행 방식

1. **기획서 먼저** — 화면 만들기 전에 위 체크리스트 기준으로 명세 정리
2. **Mock 데이터** — 실제 API 없이도 동작하도록 `mockData.js` 영역 분리
3. **상태 시뮬레이션** — 로딩/에러/빈상태 모두 토글로 확인 가능하게
4. **반응형 확인** — 모바일/태블릿/데스크탑 3개 뷰포트에서 확인
5. **GitHub Pages 배포 확인** — `index.html` 단일 파일로 동작 검증
6. **README.md** — 화면 목록, 사용 라이브러리, 배포 방법 명시

---

## 7. Confluence 업데이트 원칙 (작업 결과 문서화 시)

- **섹션 단위로 수정** — 전체 교체 금지, 변경 섹션만
- **기존 상세 내용 절대 요약 금지** — "기존 내용 유지" 같은 플레이스홀더 금지
- **업데이트 전 현재 페이지 전체 내용 확인** — `getConfluencePage`로 읽은 후 수정
- **누락 셀프 체크** — "이전에 있던 섹션이 전부 포함되어 있는가" 확인

---

## 8. 코드 스타일

- 변수명/함수명은 영어, 주석은 한국어 OK
- 함수는 단일 책임 원칙
- 매직 넘버 금지 — 상수로 빼기
- console.log는 배포 전 제거 (또는 debug 플래그)
- 한 파일이 너무 커지면 섹션 주석으로 구분

```js
// ============================================
// 1. CONSTANTS & CONFIG
// ============================================

// ============================================
// 2. MOCK DATA
// ============================================

// ============================================
// 3. UTILITIES (CSV, PDF, Date)
// ============================================

// ============================================
// 4. COMPONENTS
// ============================================

// ============================================
// 5. MAIN APP
// ============================================
```

---

## 9. 셀프 체크리스트 (제출 전)

- [ ] 모바일에서 깨지지 않는가?
- [ ] 모든 버튼이 클릭 시 동작이 정의되어 있는가?
- [ ] 로딩/빈/에러 상태가 모두 구현되어 있는가?
- [ ] CSV/PDF 다운로드가 실제로 동작하는가?
- [ ] 날짜 필터가 동작하고 초기화 가능한가?
- [ ] Toast/Modal/Confirm이 모두 작동하는가?
- [ ] API 명세가 주석으로 명시되어 있는가?
- [ ] 버튼이 찌그러져 보이지 않는가? (min-width 적용)
- [ ] 간격이 4/8/12/16/24 스케일을 지키는가?
- [ ] GitHub Pages에 올렸을 때 동작하는가?

---

**마지막 원칙: 개발자가 이걸 받아서 "아 이대로 만들면 되겠네"라고 느낄 수 있어야 한다.**
