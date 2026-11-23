"""대시보드용 데이터(data/dashboard_data.json): 기존 대시보드 형식 재현, 새 항목, 파일이 데이터와 맞는지."""
import importlib.util
import json
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from calc_engine.data import DEFAULT_DATA, load_sales_csv, load_store_csv  # noqa: E402

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bdd", HERE / "scripts" / "build_dashboard_data.py")
bdd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bdd)

sales, stores = load_sales_csv(DEFAULT_DATA), load_store_csv()
area_map = pd.read_csv(HERE.parent / "data" / "area_map.csv", dtype=str)
dong_rank = pd.read_csv(HERE / "data" / "dong_rank.csv", dtype={"기준_년분기_코드": str, "행정동_코드": str})


def areas(latest):
    return {a["id"]: a for a in bdd.build(sales, stores, area_map, latest, dong_rank)["areas"]}


def test_reproduces_existing_dashboard_format_2025q4():
    # dashboard/index.html AREAS의 홍대 값 (2025Q4 기준) — 같은 키·같은 단위로 재현돼야 함
    h = areas("20254")["hongdae"]
    assert h["rank"] == 8 and h["dongs"] == ["서교동"]
    assert h["sales"] == [3501.6, 3597.3, 3673.8, 3764.1, 3465.7, 3540.1, 3598.3, 3688.9]
    assert h["day"] == [430.6, 458.7, 524.0, 501.1, 582.7, 704.1, 487.6]
    assert h["band"] == [285.0, 194.5, 689.1, 799.1, 1199.0, 522.2]
    assert h["age"] == [111.0, 1195.4, 852.5, 531.3, 506.7, 269.6]
    assert (h["male"], h["female"], h["weekday"], h["weekend"]) == (1537.9, 1928.6, 2497.1, 1191.7)
    assert h["cafe"] == [7.5, 277.7, 5, 55]
    assert h["ind"][0] == ["한식음식점", 20.1, 741.1]


def test_rank_is_seoul_wide_and_null_for_multi_dong():
    a = areas("20254")
    assert (a["kondae"]["rank"], a["itaewon"]["rank"], a["jegi"]["rank"]) == (72, 74, 1)
    assert a["seongsu"]["rank"] is None


def test_new_fields_2026q2_match_site():
    h = areas("20262")["hongdae"]
    assert h["stores"] == 8783 and h["per_store"] == 1383  # 상권분석서비스 사이트 서교동 2026Q2
    assert h["avg_ticket"] == round(364_283_677_777 / sales[(sales["기준_년분기_코드"] == "20262") & (sales["지역"] == "홍대")]["당월_매출_건수"].sum())


def test_industry_stores_2026q2():
    a = areas("20262")
    # 커피-음료 2026Q2: 성수 596곳·월 956만 원, 명동 323곳·월 2,373만 원 (stores_areas.csv · sales_areas.csv 직접 합계)
    assert a["seongsu"]["cafe_store"] == [596, 956]
    assert a["myeong"]["cafe_store"] == [323, 2373]
    for x in a.values():
        assert [r[0] for r in x["ind_store"]] == [r[0] for r in x["ind"]]  # ind와 같은 업종·같은 순서
        assert sum(r[1] for r in x["ind_store"]) <= x["stores"]


def test_industry_per_store_matches_engine():
    # 계산 엔진 per_store(업종 필터)와 같은 값 — 대시보드 숫자와 펄이 숫자가 어긋나지 않게
    from fastapi.testclient import TestClient
    from calc_engine.main import app
    client = TestClient(app)
    a = areas("20262")
    for area_id, region in [("seongsu", "성수"), ("hongdae", "홍대")]:
        for name, n, per in a[area_id]["ind_store"][:3] + [["커피-음료", *a[area_id]["cafe_store"]]]:
            res = client.post("/calculate", json={
                "spec_version": "1.1", "request_id": "d-1", "dataset_id": "commercial_area_v1",
                "metrics": [{"column": "est_sales", "op": "per_store"}],
                "filters": [{"column": "region", "op": "eq", "value": region},
                            {"column": "industry", "op": "eq", "value": name}],
                "period": {"start": "2026-04", "end": "2026-06"}}).json()
            assert round(res["results"][0]["values"]["est_sales.per_store"] / 1e4) == per, (region, name)


def test_cautions():
    a = areas("20262")
    assert any("4개 묶음" in c for c in a["seongsu"]["cautions"])
    assert any("수산물판매" in c for c in a["nr2"]["cautions"])
    assert a["hongdae"]["cautions"] == []


def test_market_type_matches_dashboard_rule():
    # 대시보드 TYPES: 1위 업종이 청과·수산·반찬·육류·축산·농산·건어물·도매면 시장·도매형 (2026Q2 기준 6곳)
    a = areas("20262")
    market = sorted(x["name"] for x in a.values() if x["type"] == "market")
    assert market == sorted(["제기동", "노량진2동", "가락1동", "노량진1동", "영등포동", "독산1동"])
    assert all(any("시장·도매형" in c for c in x["cautions"]) for x in a.values() if x["type"] == "market")
    assert all(not any("시장·도매형" in c for c in x["cautions"]) for x in a.values() if x["type"] == "city")


def test_committed_file_is_up_to_date():
    latest = sales["기준_년분기_코드"].max()
    expected = bdd.build(sales, stores, area_map, latest, dong_rank)
    saved = json.loads((HERE / "data" / "dashboard_data.json").read_text(encoding="utf-8"))
    assert saved == json.loads(json.dumps(expected, ensure_ascii=False))
    assert saved["meta"]["latest_quarter"] == "26Q2" and len(saved["areas"]) == 20
