# AIPAL – A: 3D 상권 대시보드

`index.html` 한 파일. 빌드 없이 정적으로 열거나 배포한다 (Vercel이면 Root Directory = `dashboard`).

- 데이터: 서울 열린데이터광장 「상권분석서비스(추정매출-행정동)」 OA-22175, 「상권분석서비스(점포-행정동)」 OA-22172. C 엔진이 만든 파일을 `scripts/embed_data.py` 로 `index.html` 안에 넣는다 (아래 "데이터 넣기")
  - 리포트 20곳: 패널의 순위·추이·히트맵·질문 답변 대상 (굵은 탑). 최신 분기 매출 순서
  - 지도에 더 세운 행정동 80곳: 2025Q4 서울 행정동 매출 18–103위 중 위 20곳에 안 든 곳으로 골랐다 (가는 탑, 누르면 그 동의 리포트). 위치는 행정동 경계(vuski/admdongkor ver20251231)의 면적 중심
  - 분기 표시(헤더·순위·추이·SQL·펄이 답변)는 데이터의 `meta.quarters` 를 따른다. 지도 80곳의 분기가 다르면(`EXTRA_QUARTERS`) 그 동은 자기 분기로 표시하고, 여러 동을 비교하는 답변은 모두에게 있는 분기로 맞춘다
- 지도: three.js r128, 실제 표고(AWS Terrain Tiles, SRTM 기반, 높이 4배 강조)와 낮은 지대에서 뽑은 한강
- 큰 건물 높이 = 선택한 시간대 매출. 땅 높이는 매출에 더하지 않는다. 작은 건물은 배경 장식

## 데이터 넣기

```bash
python dashboard/scripts/embed_data.py          # 저장소 루트에서
python dashboard/scripts/embed_data.py --check  # 바뀔 내용만 확인
```

- `calc_engine/data/dashboard_data.json` (리포트 20곳) → `index.html` 의 `const DATA_META=` / `const AREAS=` 줄
- `calc_engine/data/dashboard_data_extra.json` (지도 80곳, 있을 때만) → `const EXTRA=` / `const EXTRA_QUARTERS=` 줄
- 지도 좌표(`pos`)와 구 이름(`gu`)은 지금 `index.html` 값을 id 로 붙인다. 숫자는 C 파일 그대로
- 리포트의 "점포 · 객단가"(점포 수, 점포당 월매출, 객단가, 개업률·폐업률·프랜차이즈 비율)와 주의 문구(`cautions`)는 이 데이터에서 나온다. 순위·중간값은 점포 데이터가 있는 동 전체와 비교한다
- 데이터를 넣은 뒤 `sw.js` 의 `VERSION` 을 올린다

## 상권 ↔ 행정동 매핑

`data/area_map.csv`: 대시보드 20곳(`area_id`)이 어떤 행정동(`dong_code`, OA-22175의 `행정동_코드`)을 합친 것인지. `spec_region` 은 계산 규격(B·C)의 지역명(성수·홍대·건대·강남·이태원). 신사동은 서울에 두 곳이라 코드(강남구 `11680510`)로 구분해야 한다.

## 가게 검색 (리포트 20곳)

상권 리포트의 "가게 검색"은 그 상권에 영업 중인 가게를 상호·업종·층으로 찾는다. 예: `카페`, `1층 미용실`, `지하 노래`, `스타벅스`. 대분류 버튼으로 거르고, 찾은 가게 수와 많은 업종을 함께 보여준다. 업종 이름이 검색어와 같은 가게가 먼저 나온다.

- 데이터: 공공데이터포털 「소상공인시장진흥공단_상가(상권)정보」 (15083033, 분기 갱신, 이용 제한 없음). 지금 파일은 2026-09-30 기준
- 대시보드 20곳과의 대응은 `data/area_map.csv` 의 `dong_code`(행정동 코드). 상가정보에도 같은 8자리 행정동 코드가 있어 23개 동이 모두 맞는다 (99,735곳)
- 파일: `dashboard/stores/{area_id}.json` 상권마다 하나. 상권을 열 때만 불러오고, 서비스 워커가 한 번 받은 파일은 저장해 둔다
- 다시 만들기: zip 안의 서울 CSV로 `python data/build_stores.py <상가(상권)정보_서울_YYYYMM.csv> <기준일 YYYY-MM-DD>`. 원본(서울 약 300MB)은 git에 넣지 않는다
- 주의: 층 정보가 없는 가게가 약 3분의 1이고, 원본의 층 표기가 제각각이다 (`B1`·`지`·`반지층` 등). 업소 목록이라 사무실(과학·기술)도 들어 있다. 매출 데이터(OA-22175)와 기준 시점이 다르다. 펄이와 B·C는 이 데이터를 쓰지 않는다

## 앱으로 설치 (PWA)

`manifest.webmanifest`, `sw.js`, 아이콘 4개. https 주소(Vercel)나 localhost 에서 열면 브라우저 메뉴의 "홈 화면에 추가"/"앱 설치"로 앱처럼 쓸 수 있다. 한 번 열어 둔 뒤에는 오프라인에서도 지도와 내장 데이터가 보인다 (three.js·폰트도 저장). B 분석 API 요청은 서비스 워커가 건드리지 않는다. 화면을 바꾸면 `sw.js` 의 `VERSION` 을 올려야 예전 저장본이 지워진다.

## 로컬에서 보기

```bash
python3 -m http.server 8765 --directory dashboard
```

http://localhost:8765 (API 없이도 동작한다)

## B 분석 API 연결

지도 오른쪽 아래에 떠 있는 로봇 **펄이**를 누르면 질문 말풍선이 나오고, 고르면 대화 창이 열려 답한다. 대화 창에 직접 입력한 질문은 `POST {API}/api/dashboard/analyze` 로 보낸다 (`docs/DASHBOARD_API.md`).

API 주소: `index.html` 의 `<meta name="aipal-api" content="self">` — 페이지와 같은 주소로 보낸다. B는 API 키(`X-API-Key`)를 요구하므로, Vercel 서버 함수가 키를 붙여 B로 전달한다 (키는 브라우저로 내려가지 않는다).

- `api/dashboard/analyze.js`: `POST /api/dashboard/analyze` → 키를 붙여 B로 전달 (B `docs/b-role/a-proxy/` 예시 그대로)
- `api/health.js` + `vercel.json` 의 rewrite: `GET /health` → B `/health` (키 불필요)
- Vercel → Project Settings → Environment Variables (Production·Preview): `B_API_URL` = B ngrok 주소(끝 `/` 없이), `B_API_KEY` = B가 전달한 키. 바꾼 뒤 재배포해야 적용된다
- `vercel.json`: 함수 최대 실행 150초 (대시보드 대기 시간과 같음)

다른 주소를 쓰려면:

1. 주소창: `http://localhost:8765/?api=http://127.0.0.1:8000` (이 브라우저에 기억됨, `?api=` 로 기본값으로 되돌림, `?api=off` 로 API 끔). 로컬 `http.server` 에는 서버 함수가 없으므로 로컬에서 B를 쓰려면 이 방법을 쓴다
2. `<meta name="aipal-api">` 를 비우면 `start.ps1` 의 ngrok 주소(`https://bullion-predefine-phony.ngrok-free.dev`)로 직접 보낸다 (B가 키를 요구하면 401)

| API 응답 | 대시보드 동작 |
|---|---|
| 200 `{area, sql, text}` | 답변 표시, `area` 상권으로 지도 이동 (`geondae` → 대시보드 `kondae` 매핑), `sql` 이 비면 "SQL 없이(pandas) 계산" 표시 (말풍선의 "계산 방식 보기") |
| 200 + Mock | `테스트용 Mock 데이터 · 실제 분석 결과 아님` 배지 (헤더 `X-Is-Mock` 또는 `text` 접두어로 판단) |
| 422 `needs_clarification` | `clarification_question` 을 그대로 보여줌, 계산 안 함 |
| 401 / 5xx / 연결 실패 / 150초 초과 | 사유를 표시하고, 대시보드 내장 데이터로 답할 수 있는 질문이면 그 답을 "대시보드 데이터로 답했어요" 표시와 함께 보여줌 |

`text` 는 HTML로 해석하지 않고 글자 그대로 넣는다. 펄이의 질문 말풍선은 API를 거치지 않고 내장 데이터로 바로 답한다.

직접 입력한 질문에 성수·홍대·건대·강남·이태원 밖의 동(예: 한강로동, 명동)이 들어 있으면 API로 보내지 않고 대시보드 내장 데이터(최신 분기)로 답한다. B·C가 아직 그 5곳만 계산하기 때문이다. API가 조건을 다시 물으면(422) 원문은 접어 두고, 답할 수 있는 예시 질문("{지역} {업종} 분기별 매출 추이 보여줘")을 눌러서 다시 물을 수 있게 보여준다.

### B 쪽 설정 (서버 `.env`)

- `CORS_ORIGINS` 에 대시보드 주소 추가: 예) `http://localhost:8765,https://<vercel 주소>`
- `X-Is-Mock` 헤더를 브라우저가 읽으려면 `CORSMiddleware(..., expose_headers=["X-Is-Mock","X-Data-Source"])` 필요 (없어도 `text` 접두어로 Mock 표시는 됨)
- ngrok 무료 주소는 브라우저 경고 페이지가 끼므로 대시보드가 `ngrok-skip-browser-warning` 헤더를 보낸다
- `API_KEY` 는 이 페이지에 넣지 않는다. 키는 Vercel 환경변수 `B_API_KEY` 에만 있고 `api/dashboard/analyze.js` 가 붙인다

## 로봇 펄이 (3D)

`pearl/pearl_robot.blend` 를 블렌더로 모델링하고, `pearl.glb`(3D)와 표정 이미지 4장(`pearl_idle/think/talk/happy.webp`), 얼굴(`pearl_face.webp`)로 내보냈다. 페이지 안에는 같은 파일이 base64 로 들어 있어 따로 불러오지 않는다 (이 폴더는 원본 보관용). 데스크톱은 실제 3D(고개가 마우스를 따라가고, 깜빡이고, 생각 중엔 눈을 굴리고, 말할 땐 입이 움직임), 폰·느린 기기·동작 줄이기 설정에서는 렌더 이미지로 보인다.
