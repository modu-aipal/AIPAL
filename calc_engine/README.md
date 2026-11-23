# C: 계산 엔진

B의 AI 분석 API가 `POST {CALC_ENGINE_URL}/calculate`로 호출하는 계산 엔진. 숫자는 모두 여기서 pandas로 계산한다.
규격: `docs/CALC_API.md`(v1.0) + `docs/CALC_API_v1.1.md`(실제 데이터에 맞춘 처리와 확장 제안). 데이터 정의: `docs/DATA.md`.

## 실행 (저장소 최상단에서)
```powershell
.\.venv\Scripts\pip install -r calc_engine\requirements.txt
.\.venv\Scripts\python -m uvicorn calc_engine.main:app --port 8100
```
- B 서버의 `.env`: `CALC_MODE=http`, `CALC_ENGINE_URL=http://localhost:8100` (기본값 그대로)
- 확인: http://127.0.0.1:8100/health , http://127.0.0.1:8100/docs

## 테스트
```powershell
.\.venv\Scripts\python -m pytest calc_engine
```
- `test_data.py`: 읽기·검사(빈 파일, 숫자 아닌 값, CP949 원본 등), 데이터 파일이 정답표와 맞는지
- `test_calculate.py`: `/calculate` 응답 형식과 계산 값을 정답표(`data/answer_key.md`)와 대조, 오류 형식
- `test_stores.py`: 점포 데이터를 사이트 값과 대조, 점포 지표·점포당 매출
- `test_b_integration.py`: **B 코드를 고치지 않고** B의 `build_request` → `HttpCalculator`(응답 검증 포함)로 이 엔진을 호출해 통과하는지
- pandas가 없는 환경에서는 건너뜀 (B 테스트에는 영향 없음)

## 폴더
```
main.py       서버 (POST /calculate, GET /health)
engine.py     규격 v1.0 + v1.1 확장 계산
data.py       CSV 읽기·검사, 컬럼 카탈로그, 업종 묶음
data/         region_map.csv, sales_areas.csv(매출), stores_areas.csv(점포), answer_key.md
scripts/      build_dataset.py, build_store_dataset.py, answer_key.py
tests/
```
