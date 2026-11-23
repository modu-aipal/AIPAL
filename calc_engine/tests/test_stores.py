"""점포 데이터(OA-22172) 연결: 데이터 파일 검사, 사이트 값 대조, /calculate 점포 지표와 점포당 매출."""
import pytest

pytest.importorskip("pandas")

from fastapi.testclient import TestClient  # noqa: E402

from calc_engine.data import load_store_csv  # noqa: E402
from calc_engine.main import app  # noqa: E402

client = TestClient(app)
st = load_store_csv()
Q4 = {"start": "2025-10", "end": "2025-12"}
Q2_26 = {"start": "2026-04", "end": "2026-06"}
SEOGYO = [{"column": "dong", "op": "eq", "value": "서교동"}]


def calc(**body):
    req = {"spec_version": "1.0", "request_id": "s-1", "dataset_id": "commercial_area_v1", **body}
    res = client.post("/calculate", json=req)
    return res.status_code, res.json()


# ---- 데이터 파일 ----

def test_store_data_shape_and_columns():
    assert st.shape == (16308, 13)
    assert st["기준_년분기_코드"].nunique() == 22  # 2021Q1~2026Q2
    assert set(st["지역"]) == {"성수", "홍대", "건대", "강남", "이태원"}
    assert (st["전체_점포_수"] == st["일반_점포_수"] + st["프랜차이즈_점포_수"]).all()


def test_seogyo_2025q4_matches_site():
    # 상권분석서비스 사이트 서교동 2025년 4분기: 점포 8,820 / 일반 8,101 / 프랜차이즈 719 / 개업 223 / 폐업 239
    s = st[(st["기준_년분기_코드"] == "20254") & (st["행정동_코드_명"] == "서교동")]
    assert (s["전체_점포_수"].sum(), s["일반_점포_수"].sum(), s["프랜차이즈_점포_수"].sum(),
            s["개업_점포_수"].sum(), s["폐업_점포_수"].sum()) == (8820, 8101, 719, 223, 239)


# ---- /calculate ----

def test_store_metrics_sum_v10():
    status, body = calc(metrics=[{"column": "store_count", "op": "sum"}, {"column": "franchise_count", "op": "sum"},
                                 {"column": "open_count", "op": "sum"}, {"column": "close_count", "op": "sum"}],
                        filters=SEOGYO, period=Q4)
    assert status == 200 and body["spec_version"] == "1.0"
    assert body["results"][0]["values"] == {"store_count.sum": 8820, "franchise_count.sum": 719,
                                            "open_count.sum": 223, "close_count.sum": 239}
    assert any(n.startswith("store_count_is_total") for n in body["results"][0]["notes"])


def test_per_store_matches_site_monthly_average():
    # 사이트 '점포당 월평균 매출': 2025Q4 1,394만 원, 2026Q2 1,383만 원
    _, q4 = calc(spec_version="1.1", metrics=[{"column": "est_sales", "op": "per_store"}], filters=SEOGYO, period=Q4)
    assert q4["results"][0]["values"]["est_sales.per_store"] == 368_888_000_781 / (8820 * 3)
    assert round(q4["results"][0]["values"]["est_sales.per_store"] / 10_000) == 1394
    _, q2 = calc(spec_version="1.1", metrics=[{"column": "est_sales", "op": "per_store"}], filters=SEOGYO, period=Q2_26)
    assert round(q2["results"][0]["values"]["est_sales.per_store"] / 10_000) == 1383


def test_per_store_region_comparison_uses_both_tables():
    _, body = calc(spec_version="1.1", metrics=[{"column": "est_sales", "op": "sum"}, {"column": "store_count", "op": "sum"},
                                                {"column": "est_sales", "op": "per_store"}],
                   group_by=["region"], period=Q2_26)
    for r in body["results"]:
        v = r["values"]
        assert v["est_sales.per_store"] == v["est_sales.sum"] / (v["store_count.sum"] * 3)
    assert body["rows_used"] == sum(r["rows_used"] for r in body["results"])


def test_open_rate_ratio_uses_total_stores():
    _, body = calc(spec_version="1.1", metrics=[{"column": "open_count", "op": "ratio"}], filters=SEOGYO, period=Q4)
    assert body["results"][0]["values"]["open_count.ratio"] == 223 / 8820


def test_cafe_alias_works_on_store_table():
    _, body = calc(metrics=[{"column": "store_count", "op": "sum"}],
                   filters=[{"column": "industry", "op": "eq", "value": "카페"}, *SEOGYO], period=Q4)
    s = st[(st["기준_년분기_코드"] == "20254") & (st["행정동_코드_명"] == "서교동") & (st["서비스_업종_코드_명"] == "커피-음료")]
    assert body["results"][0]["values"]["store_count.sum"] == s["전체_점포_수"].sum()


def test_per_store_not_allowed_on_store_metric():
    status, body = calc(spec_version="1.1", metrics=[{"column": "store_count", "op": "per_store"}], period=Q4)
    assert status == 400 and body["error"]["code"] == "UNSUPPORTED_OPERATION"


def test_health_reports_store_rows():
    assert client.get("/health").json()["store_rows"] == 16308
