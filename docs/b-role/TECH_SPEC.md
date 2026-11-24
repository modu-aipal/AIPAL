# AI 분석 서버(B) — 기술 명세서

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 |
| 작성일 | 2026-11-24 |
| 기준 커밋 | main `bbb905a` (PR #31까지 병합) |
| 관련 문서 | [PRD.md](./PRD.md) · `docs/DASHBOARD_API.md` · `docs/CALC_API.md` · `docs/CALC_API_v1.1.md` |

---

## 1. 기술 스택

| 구분 | 사용 | 비고 |
|---|---|---|
| 서버 | Python, FastAPI (`app/main.py`), 포트 8000 | C 엔진(8100)과 같은 언어·프레임워크 |
| 모델 | Ollama `llama3.1:8b` (로컬, `OLLAMA_MODEL`) | 계획 초안·해석문 보조. 유료 API 없음 |
| 스키마 | Pydantic (`app/schemas/`) | 계획·계산 요청/응답을 형식으로 고정 |
| 계산 연결 | `app/services/calc/` (http 어댑터, mock 어댑터) | `CALC_MODE=http`가 실제, `mock`은 개발·테스트용 |
| 테스트 | pytest, FastAPI TestClient | 서버·모델 없이 요청~응답 확인 |
| 평가 | `scripts/eval_planner.py` + 질문셋 JSON | 질문 해석 회귀 확인 |
| 공개 | ngrok 무료 도메인 → B(8000) | 팀장 PC 기준 |

### 1.1 의도적으로 쓰지 않는 것

| 쓰지 않는 것 | 이유 |
|---|---|
| 모델이 숫자를 계산·작성하는 것 | 숫자는 C만. 모델은 해석(계획 초안)과 문장 다듬기만 |
| 모델 출력을 그대로 신뢰 | 코드 규칙이 읽은 값이 우선, 계획은 검증 후에만 계산으로 넘김 |
| 외부 유료 AI API | 비용·키 관리 |
| 서버 대화 저장·DB | 개인정보·운영 부담. 이어 묻기는 A가 보낸 `history`로 대체 |
| 자유 SQL·코드 실행 | 허용된 계산 연산만 요청 (C 규격) |

---

## 2. 시스템 구성

```
A (Vercel 서버 함수: X-API-Key 부착)
      │  POST /api/dashboard/analyze {question, history}
      ▼
B  app/api/routes/dashboard.py
   ├─ core/security.py        X-API-Key 검증 (/health 제외)
   ├─ services/planner.py     질문 → AnalysisPlan (모델 초안 + 규칙 검증)
   │    ├─ understand.py, metrics.py, periods.py, areas.py, dataset.py   (지역·업종·기간·지표 읽기)
   │    ├─ composition.py, judgment.py, data_facts.py, follow_up.py      (특수 질문 유형)
   │    └─ ollama.py          모델 호출 (30초/400토큰, 실패하면 건너뜀)
   ├─ services/calc/          build_request → C /calculate → verify_result
   ├─ services/ranking.py     순위·하한·표시용 정렬
   ├─ services/answer_extras.py  창업·수입: 같은 조건 순위, 이어 물어볼 질문
   └─ services/compose.py · explain.py   답변 문장 구성 {area, sql, text}
      │
      ▼
C  POST /calculate (8100)
```

### 2.1 핵심 설계 원칙

1. **숫자는 C에서만.** B는 단위·반올림 같은 표시 변환만 한다.
2. **코드 값이 모델 값을 이긴다.** `evaluate(question, draft, ...)`는 순수 함수이고 모델 없이도 같은 규칙으로 동작한다.
3. **애매하면 이어받지 않고 되묻는다.** 엉뚱한 조건이 붙는 것보다 안전하다.
4. **안내한 질문은 반드시 통과해야 한다.** 제안 질문은 서버가 직접 `evaluate`로 확인(`verify_questions`)한 것만 보여 준다.
5. **A·C 파일은 수정하지 않는다.** 필요한 것은 이슈·PR 문서로 요청한다 (이슈 #26: A의 `history` 전송).

---

## 3. API

| 경로 | 용도 |
|---|---|
| `POST /api/dashboard/analyze` | A 대시보드용 {area, sql, text} (규격: `docs/DASHBOARD_API.md`) |
| `POST /api/plan` | 계획만 보기 (디버그) |
| `POST /api/calc`, `POST /api/analyze` | 계산·분석 구조화 응답 |
| `POST /api/chat` | 일반 대화 (분석 아님) |
| `GET /health` | 상태·모델·지원 지역 `regions`·최신 분기 (인증 없음) |

### 3.1 요청 (`DashboardRequest`)

```
POST /api/dashboard/analyze
X-API-Key: <키>
{"question": "...", "history": ["직전 질문", ...]}     ← history 는 선택
```

- `history`: 문자열만, 빈 것 제외, 각 200자, 최근 3개 (`clean_history`).

### 3.2 응답

| 상황 | 응답 |
|---|---|
| 정상 | 200 `{area, sql, text}` + 헤더 `X-Is-Mock`·`X-Data-Source` |
| 데이터 설명 | 200, `area=""`, `sql=""`, 설명 `text` |
| 되묻기 | 422 `needs_clarification` + `detail`(이유 + 검증된 제안) |
| 키 없음·틀림 | 401 |
| 계산 실패 | 5xx 사유 (숫자 없음) |

---

## 4. 질문 해석 (`planner.evaluate`)

### 4.1 순서

1. 이어 묻기 판별 (`follow_up.is_follow_up`) → 직전 질문에서 **빠진 조건만** 상속 (`build_context`).
2. 모델 초안(`PlanDraft`)을 받는다 (실패해도 진행).
3. 특수 질문 순서로 규칙 검사: 구성비 → 생존·위험 → 전망 → 수입 → 비교 → 위치 → 창업 → 경쟁.
4. 지역·업종·기간·지표를 규칙으로 읽는다. 읽은 값이 모델 값보다 우선.
5. 기간 범위(2021Q1 ~ 최신 분기) 검사, 필수 조건이 빠지면 되묻기.
6. `AnalysisPlan`(조회·순위·비교·추이 등) 확정.

### 4.2 주요 규칙

| 항목 | 규칙 |
|---|---|
| 점포당 | 점포·가게·매장·업소 + 당·별·마다·하나당·대비·나눠, "가게 평균 매출" (`metrics.is_per_store`) |
| 합계 | "합계·총" 표현이면 합계 (`TOTAL_WORDS`) |
| 전년 대비 | `YOY_RE` → 증감 지표를 넣고 `growth_basis="year_over_year"`, 기준 기간을 요청에 명시 |
| 판단 표현 | startup·survival·danger·income·outlook·compare·invest·success (`judgment.py`), 위험 표현은 "유망·희망"을 제외 |
| 구성비 | 주중·주말·요일·성별·연령·시간대 등 (`composition.py`), 여러 항을 한꺼번에 읽음 |
| 데이터 설명 | 13개 주제 (`data_facts.py`), 분석어(매출·순위·점포 수…)가 있고 묻는 말(뭐·언제·어디·왜…)이 없으면 건너뜀 |
| 이어 묻기 | 이어 묻는 표현이 있고 새 질문에 조건이 빠졌고 그 질문 유형이 필요로 할 때만. 생략형은 ≤14자·≤2어절 |
| 업종 별칭 | 부동산·공인중개사→부동산중개업, 한식→한식음식점, 치킨, 빵집·베이커리, 피시방, 헬스장 등 |

### 4.3 순위 하한 (`ranking.py`)

| 순위 종류 | 조건 | 이유 |
|---|---|---|
| 증감률·점포당 | 매출 합계 1억 원 이상 그룹만 | 매출이 작으면 값이 크게 흔들림 |
| 개업률·폐업률 | 점포 평균 30개 이상, 매출 0 초과 | 표본이 작으면 비율이 왜곡 |

제외한 사실은 답변에 밝힌다.

---

## 5. 계산 요청·검증

| 항목 | 내용 |
|---|---|
| 요청 | `build_request(plan)` → 규격 1.0 (점포당·비율이면 1.1) |
| 증감 기준 | `growth.baseline_period`를 B가 명시 (전 분기 / 전년 같은 분기) |
| 검증 | `verify_result`: 요청한 지표·그룹이 모두 있는지, 값 형식·null 사유 확인 |
| Mock | `CALC_MODE=mock`일 때만. `APP_ENV=production`에서는 차단 |
| 연산 | sum, avg, growth_rate, per_store, ratio (share는 사용 안 함) |

---

## 6. 답변 구성

### 6.1 기본 형식
결론 한 줄 → 목록(순위·값) → 해석 한두 줄 → `※` 가정·기준·한계.

### 6.2 창업·수입 질문 (한 지역 조회, `kind=startup|income`)
1. 결론: "성수의 카페는 점포 598개, 한 곳당 월평균 매출 888만 원입니다 (2026년 2분기)."
2. 같은 조건에서 순위 (점포당 매출·점포 수 각각 20곳 중 몇 위) — `build_rank_plan`으로 C에 모든 지역을 한 번 더 요청해 정렬. 실패하면 순위 줄만 뺀다.
3. 매출 증감(비교 기준 포함), 매출 합계.
4. `→ 이어서 물어보기:` 서버가 통과를 확인한 질문 최대 3개.
5. 한계 문구(`disclaimers`).

---

## 7. 이어 묻기 (`follow_up.py`)

- 서버는 대화를 저장하지 않는다. A가 `history`를 보낸다.
- `build_context`: history 질문들을 같은 규칙으로 다시 읽어 **마지막으로 성공한 계획**의 지역·업종·기간(말로 명시한 것만)·지표를 꺼낸다 (모델 호출 없음).
- 새 질문에 없는 조건만 채우고, 채웠으면 답변에 "※ 기준: 이전 질문의 … 이어서 적용".
- 순위 질문·정보 질문은 이어받지 않는다.

---

## 8. 보안

| 항목 | 내용 |
|---|---|
| 인증 | `X-API-Key` 헤더, `secrets.compare_digest`, `/health`만 열어 둠 (`core/security.py`) |
| 키 위치 | 서버 `.env`(`API_KEY`, git 제외)와 A의 Vercel 환경변수 `B_API_KEY`. 클라이언트 코드에는 넣지 않는다 |
| CORS | `CORS_ORIGINS` 환경변수 (대시보드 주소), `X-Is-Mock`·`X-Data-Source` 노출 |
| 입력 | 질문 1~1000자, history는 문자열만·최근 3개·각 200자 |
| 데이터 | 질문 원문을 저장·로깅하지 않음 |
| 모델 | 프롬프트에 사용자 질문을 데이터로만 넣고, 모델 출력은 계획 형식 검증을 통과해야 사용 |

---

## 9. 설정 · 운영

### 9.1 환경 변수 (`.env`, 예: `.env.example`)

`APP_HOST/APP_PORT`, `CORS_ORIGINS`, `OLLAMA_BASE_URL`·`OLLAMA_MODEL`·`OLLAMA_TIMEOUT_SECONDS`, `CALC_ENGINE_URL`·`CALC_MODE`·`CALC_DATASET_ID`, `API_KEY`, 최신 분기 대체값(평소엔 C `/health`에서 읽음).

### 9.2 실행

1. C 엔진 8100 실행 (`calc_engine`)
2. B 서버 8000 실행 (`start.ps1`)
3. ngrok이 8000으로 연결

### 9.3 병합 후 재시작
main 병합 → 로컬을 `main`으로 동기화 → B(8000)만 재시작 → `/health` 확인(로컬·ngrok) → 키 없이 호출하면 401인지 확인. C와 ngrok은 건드리지 않는다.

---

## 10. 확인 방법

| 대상 | 방법 |
|---|---|
| 전체 | `pytest` (저장소 전체 434개 통과, 1개 건너뜀, 2026-11-24) |
| 질문 해석 | `python scripts/eval_planner.py --rules-only` (기본 116문항 규칙만 115 통과), `--cases scripts/eval_questions_heldout.json` (처음 본 표현 21문항) |
| 숫자 | 답변 숫자를 C 정답표·`sales_areas.csv` 직접 계산과 대조 |
| 연동 | A 화면 또는 `curl`로 `POST /api/dashboard/analyze` (본 주소 경유·ngrok 직접 모두) |
| 접근 제한 | 키 없이 호출 → 401 |

---

## 11. 미결정 사항

미결정 사항은 [PRD.md](./PRD.md) §14 한 곳에서 관리한다. 이 문서와 관련 있는 것:

| PRD 번호 | 항목 | 관련 절 |
|---|---|---|
| Q-B01 | `reason`·`suggested_questions`를 A 화면에 쓸지 | §3.2 |
| Q-B02 | API 키 교체 여부 | §8 |
| Q-B03 | 모델 교체 여부 | §1 |
| Q-B04 | 처음 본 표현을 규칙에 더 넣을지 | §4 |
