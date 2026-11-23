# 계산 엔진 API v1.1 제안 (C → B)

`docs/CALC_API.md`(v1.0)는 실제 데이터를 보기 전에 만든 규격이라, 실제 데이터와 다른 가정이 몇 가지 있다.
C 엔진(`calc_engine/`)은 **v1.0 요청·응답 틀을 그대로 지키면서** 실제 데이터에 맞게 아래처럼 처리한다.
**B 코드를 고치지 않아도 지금 그대로 연결된다** (`calc_engine/tests/test_b_integration.py`: B의 `build_request` → `HttpCalculator` → `verify_result` 통과).

## 1. 데이터와 v1.0 가정의 차이, 엔진 처리
| v1.0 가정 | 실제 데이터 (docs/DATA.md) | 엔진 처리 (지금 동작) | B에 제안 |
|---|---|---|---|
| 시간 `year_month` (월) | **분기만 있음** | `period`가 분기 경계(start 1·4·7·10월, end 3·6·9·12월)면 해당 분기로 계산, 아니면 `INVALID_REQUEST`. `group_by: ["year_month"]`는 분기로 묶고 값은 `"2025Q4"`, notes `quarter_granularity` | 데이터셋 메타의 시간 컬럼을 `quarter`로, 기간을 분기 경계로 만들기 |
| 업종 7개 묶음 (카페·음식점…) | **실제 63개 업종** (20곳 기준. 처음 5곳은 62개) | 실제 업종 이름과 묶음 이름 둘 다 받음. 묶음은 실제 업종으로 펼치고 notes `industry_group: 카페=커피-음료` | `allowed_values`를 실제 업종으로 넓히거나 묶음 유지. 묶음 매핑은 docs/DATA.md 4절(팀 검토) |
| `store_count` | 점포 데이터(OA-22172) 연결로 **제공** | 전체 점포 수(프랜차이즈 포함). `franchise_count`, `open_count`, `close_count`, `general_store_count`도 있음 | 데이터셋 메타 그대로 사용 가능 |
| `avg` (뜻 미정) | — | **분기당 평균** = 기간 합계 ÷ 기간 내 분기 수. `methods[].formula`에 명시 | 이 정의로 합의 |
| 비율 없음 | 주말·야간·성별·연령 비중 필요 | v1.1 확장 op (아래 2절) | 필요해지면 `AggOp`에 추가 |

## 2. v1.1 확장 op (B가 보내지 않으면 v1.0과 똑같이 동작)
| op | 계산 | 분모 |
|---|---|---|
| `ratio` | 그룹별 sum(지표) ÷ sum(분모) | 매출 구성 지표(주중·주말·요일·시간대) → `est_sales` / 성별 → 남성+여성 / 연령 → 연령 6개 합 (**법인 매출이 빠져 있어 총매출로 나누면 틀림**) |
| `share` | 그룹별 sum(지표) ÷ 같은 조건 전체 그룹의 sum(지표) | — |
| `per_store` | 그룹별 sum(매출 지표) ÷ (sum(store_count) × 3) = **점포당 월평균** (사이트 '점포당 월평균 매출'과 같은 정의) | 같은 조건의 전체 점포 수 × 3개월. 매출 지표에만 |
- 확장 op를 쓴 응답은 `spec_version: "1.1"`. 분모가 0이면 값 `null` + notes `denominator_zero`

## 3. notes 코드 (행마다 붙음)
| 코드 | 뜻 |
|---|---|
| `baseline_zero`, `baseline_missing` | v1.0과 같음 (growth_rate 값 null 사유) |
| `quarter_granularity: …` | year_month 요청을 분기로 계산함 |
| `excludes_corporate_sales: …` | 성별·연령 지표. 법인 매출이 빠져 있어 분모가 성별·연령 합계 |
| `industry_group: 카페=커피-음료` | 업종 묶음 이름을 실제 업종으로 펼침 |
| `store_count_is_total: …` | 점포 지표 사용. 점포 수는 프랜차이즈 포함 전체 |
| `region_dong_count: 4` | 지역으로 묶을 때 그 지역의 포함 동 개수 |

## 4. 오류 HTTP 상태
`DATASET_NOT_FOUND`·`NO_DATA` 404 / `INTERNAL_ERROR` 500 / 나머지 400. 본문은 항상 v1.0 오류 형식(`status: "error"` + `error`).
