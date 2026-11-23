"""POST /calculate: 규격 v1.0 응답 모양과, 계산 값이 정답표와 같은지."""
import pytest

pytest.importorskip("pandas")

from fastapi.testclient import TestClient  # noqa: E402

from calc_engine.main import app  # noqa: E402

client = TestClient(app)
Q4 = {"start": "2025-10", "end": "2025-12"}


def calc(**body):
    req = {"spec_version": "1.0", "request_id": "t-1", "dataset_id": "commercial_area_v1", **body}
    res = client.post("/calculate", json=req)
    return res.status_code, res.json()


def by_group(body, key):
    return {tuple(r["group"].values()): r["values"][key] for r in body["results"]}


# ---- 정답표와 비교 ----

def test_q2_region_sum_and_v10_shape():
    req = {"metrics": [{"column": "est_sales", "op": "sum"}], "group_by": ["region"],
           "filters": [{"column": "region", "op": "in", "value": ["성수", "홍대", "건대", "강남", "이태원"]}], "period": Q4}
    status, body = calc(**req)
    assert status == 200 and body["status"] == "ok" and body["is_mock"] is False
    assert body["spec_version"] == "1.0" and body["request_id"] == "t-1"
    assert by_group(body, "est_sales.sum") == {
        ("강남",): 519_254_348_394, ("건대",): 84_693_721_210, ("성수",): 312_913_739_756,
        ("이태원",): 83_354_980_644, ("홍대",): 368_888_000_781,
    }
    a = body["applied"]
    assert a["operations"] == req["metrics"] and a["group_by"] == ["region"] and a["period"] == Q4
    assert a["baseline_period"] is None and {"est_sales", "region"} <= set(a["columns_used"])
    assert sum(r["rows_used"] for r in body["results"]) == body["rows_used"]
    assert any(n.startswith("region_dong_count: 4") for r in body["results"] if r["group"]["region"] == "성수" for n in r["notes"])


def test_v10_example1_cafe_alias_maps_to_real_industry():
    # docs/CALC_API.md 예시 1과 같은 요청 ('카페' 묶음 → 커피-음료), 기간만 2025년 4분기로
    status, body = calc(
        time_column="year_month", metrics=[{"column": "est_sales", "op": "sum"}], group_by=["region"],
        filters=[{"column": "industry", "op": "eq", "value": "카페"},
                 {"column": "region", "op": "in", "value": ["성수", "홍대"]}],
        period=Q4,
    )
    assert status == 200
    assert by_group(body, "est_sales.sum") == {("성수",): 15_496_172_851, ("홍대",): 27_768_312_903}
    assert all("industry_group: 카페=커피-음료" in r["notes"] for r in body["results"])


def test_q4_trend_year_month_alias_groups_by_quarter():
    status, body = calc(
        time_column="year_month", metrics=[{"column": "est_sales", "op": "sum"}], group_by=["year_month"],
        filters=[{"column": "region", "op": "eq", "value": "성수"}, {"column": "industry", "op": "eq", "value": "커피-음료"}],
        period=None,
    )
    assert status == 200 and len(body["results"]) == 22  # 2021Q1~2026Q2
    assert body["results"][0]["group"] == {"year_month": "2021Q1"}
    assert body["results"][0]["values"]["est_sales.sum"] == 11_000_139_138
    assert body["results"][19]["group"] == {"year_month": "2025Q4"}
    assert body["results"][19]["values"]["est_sales.sum"] == 15_496_172_851
    assert body["results"][-1]["group"] == {"year_month": "2026Q2"}
    assert body["results"][-1]["values"]["est_sales.sum"] == 17_096_057_556
    notes = body["results"][0]["notes"]
    assert any(n.startswith("quarter_granularity") for n in notes)
    # 제공 기관 답변(2026-11-20): 2021년부터 새 기준으로 재산출 → 2023년 이전 주의 안내를 붙이지 않음
    assert not any(n.startswith("pre_2024") for n in notes)


def test_q10_growth_rate_year_over_year():
    status, body = calc(
        metrics=[{"column": "est_sales", "op": "growth_rate"}], group_by=[],
        filters=[{"column": "region", "op": "eq", "value": "이태원"}], period=Q4,
        growth={"current_period": Q4, "baseline_period": {"start": "2024-10", "end": "2024-12"}},
    )
    assert status == 200
    assert body["results"][0]["values"]["est_sales.growth_rate"] == 83_354_980_644 / 79_543_156_367 - 1
    assert body["applied"]["baseline_period"] == {"start": "2024-10", "end": "2024-12"}


def test_growth_baseline_missing_is_null_with_reason():
    q1 = {"start": "2021-01", "end": "2021-03"}
    status, body = calc(
        metrics=[{"column": "est_sales", "op": "growth_rate"}], group_by=["region"], period=q1,
        growth={"current_period": q1, "baseline_period": {"start": "2020-10", "end": "2020-12"}},
    )
    assert status == 200
    for r in body["results"]:
        assert r["values"]["est_sales.growth_rate"] is None and "baseline_missing" in r["notes"]


def test_avg_is_per_quarter_average():
    year = {"start": "2025-01", "end": "2025-12"}
    _, s = calc(metrics=[{"column": "est_sales", "op": "sum"}], filters=[{"column": "region", "op": "eq", "value": "성수"}], period=year)
    _, a = calc(metrics=[{"column": "est_sales", "op": "avg"}], filters=[{"column": "region", "op": "eq", "value": "성수"}], period=year)
    assert a["results"][0]["values"]["est_sales.avg"] == s["results"][0]["values"]["est_sales.sum"] / 4


# ---- v1.1 확장 ----

def test_ratio_weekend_share_q5():
    status, body = calc(spec_version="1.1", metrics=[{"column": "weekend_sales", "op": "ratio"}], group_by=["region"], period=Q4)
    assert status == 200 and body["spec_version"] == "1.1"
    assert by_group(body, "weekend_sales.ratio")[("이태원",)] == 37_069_364_410 / 83_354_980_644


def test_ratio_night_q9_and_gender_denominator():
    _, night = calc(spec_version="1.1", metrics=[{"column": "time_21_24_sales", "op": "ratio"}],
                    filters=[{"column": "region", "op": "eq", "value": "이태원"}], period=Q4)
    assert night["results"][0]["values"]["time_21_24_sales.ratio"] == 14_943_649_372 / 83_354_980_644
    _, g = calc(spec_version="1.1", metrics=[{"column": "female_sales", "op": "ratio"}],
                filters=[{"column": "region", "op": "eq", "value": "이태원"}], period=Q4)
    assert g["results"][0]["values"]["female_sales.ratio"] == 28_332_111_797 / (49_562_775_628 + 28_332_111_797)
    assert any(n.startswith("excludes_corporate_sales") for n in g["results"][0]["notes"])


def test_share_sums_to_one():
    _, body = calc(spec_version="1.1", metrics=[{"column": "est_sales", "op": "share"}], group_by=["dong"],
                   filters=[{"column": "region", "op": "eq", "value": "성수"}], period=Q4)
    assert abs(sum(r["values"]["est_sales.share"] for r in body["results"]) - 1) < 1e-12


# ---- 오류는 규격 형식 (status=error + error 객체) ----

@pytest.mark.parametrize("body, status, code", [
    ({"metrics": [{"column": "profit", "op": "sum"}]}, 400, "COLUMN_NOT_FOUND"),
    ({"metrics": [{"column": "est_sales", "op": "median"}]}, 400, "INVALID_REQUEST"),
    ({"metrics": [{"column": "est_sales", "op": "sum"}], "period": {"start": "2025-02", "end": "2025-12"}}, 400, "INVALID_REQUEST"),
    ({"metrics": [{"column": "est_sales", "op": "sum"}], "filters": [{"column": "region", "op": "eq", "value": "부산"}]}, 400, "INVALID_REQUEST"),
    ({"metrics": [{"column": "est_sales", "op": "sum"}], "filters": [{"column": "region", "op": "eq", "value": ["성수"]}]}, 400, "INVALID_REQUEST"),
    ({"metrics": [{"column": "est_sales", "op": "sum"}], "filters": [{"column": "industry", "op": "gte", "value": "카페"}]}, 400, "UNSUPPORTED_OPERATION"),
    ({"metrics": [{"column": "est_sales", "op": "growth_rate"}]}, 400, "INVALID_REQUEST"),
    ({"metrics": [{"column": "est_sales", "op": "sum"}], "period": {"start": "2019-01", "end": "2019-12"}}, 404, "NO_DATA"),
    ({"metrics": [{"column": "est_sales", "op": "sum"}], "dataset_id": "other"}, 404, "DATASET_NOT_FOUND"),
])
def test_errors_use_spec_format(body, status, code):
    got_status, got = calc(**body)
    assert got_status == status
    assert got["status"] == "error" and got["error"]["code"] == code and got["request_id"] == "t-1"
    assert "results" not in got


def test_q11_seogyo_2026q2_matches_site():
    # 상권분석서비스 사이트: 서교동 2026년 2분기 매출 3,642.8억 원
    status, body = calc(metrics=[{"column": "est_sales", "op": "sum"}, {"column": "est_count", "op": "sum"}],
                        filters=[{"column": "dong", "op": "eq", "value": "서교동"}],
                        period={"start": "2026-04", "end": "2026-06"})
    assert status == 200
    v = body["results"][0]["values"]
    assert v["est_sales.sum"] == 364_283_677_777
    assert round(v["est_sales.sum"] / 3 / 8783 / 10_000) == 1383  # 사이트 점포당 월평균 1,383만 원
    assert round(v["est_count.sum"] / 3 / 8783) == 582  # 사이트 월평균 매출건수 582건


def test_health():
    body = client.get("/health").json()
    assert body["rows"] == 24340 and body["quarters"] == ["20211", "20262"]
