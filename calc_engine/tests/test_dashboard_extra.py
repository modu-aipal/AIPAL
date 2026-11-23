"""대시보드 지도 80곳(data/dashboard_data_extra.json).

파일 모양 검사는 항상 돈다. 원본(calc_engine/raw/)이 있어야 하는 검사(파일이 최신인지)는 원본이 없으면 건너뛴다.
(2025Q4 기준으로 만들면 dashboard/index.html의 EXTRA 80곳 × 15항목 1,200개가 전부 일치함을 2026-11-23에 확인)
"""
import importlib.util
import json
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

HERE = Path(__file__).resolve().parents[1]
SAVED = json.loads((HERE / "data" / "dashboard_data_extra.json").read_text(encoding="utf-8"))
EXTRA_MAP = pd.read_csv(HERE / "data" / "extra_area_map.csv", dtype=str)
OLD_KEYS = ["id", "name", "dongs", "rank", "gu", "sales", "ind", "day", "band", "age",
            "male", "female", "weekday", "weekend", "cafe"]  # 대시보드 EXTRA 키 (pos는 대시보드 쪽 값)
NEW_KEYS = ["stores", "per_store", "avg_ticket", "open_rate", "close_rate", "franchise_rate",
            "dong_count", "type", "cautions", "ind_store", "cafe_store"]


def test_shape_and_keys():
    assert SAVED["meta"]["latest_quarter"] == "26Q2"
    assert SAVED["meta"]["quarters"] == ["24Q3", "24Q4", "25Q1", "25Q2", "25Q3", "25Q4", "26Q1", "26Q2"]
    assert [a["id"] for a in SAVED["areas"]] == list(EXTRA_MAP["area_id"])
    for a in SAVED["areas"]:
        assert list(a)[:5] == ["id", "name", "dongs", "rank", "gu"]
        assert set(OLD_KEYS + NEW_KEYS) == set(a)
        assert len(a["sales"]) == 8 and len(a["day"]) == 7 and len(a["band"]) == 6 and len(a["age"]) == 6
        assert a["id"] == "d" + EXTRA_MAP.set_index("area_id").loc[a["id"], "dong_code"]


def test_no_overlap_with_20_areas():
    area20 = pd.read_csv(HERE.parent / "data" / "area_map.csv", dtype=str)
    assert not set(EXTRA_MAP["dong_code"]) & set(area20["dong_code"])


def test_market_type_rule():
    import re
    rx = re.compile(r"청과|수산|반찬|육류|축산|농산|건어물|도매")
    for a in SAVED["areas"]:
        assert a["type"] == ("market" if rx.search(a["ind"][0][0]) else "city")


@pytest.mark.skipif(not (HERE / "raw" / "sales_dong_sheet_2025Q1_2026Q2.csv").exists(), reason="원본(raw/)이 없음")
def test_saved_file_is_up_to_date_with_raw():
    spec = importlib.util.spec_from_file_location("bde", HERE / "scripts" / "build_dashboard_extra.py")
    bde = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bde)
    assert json.loads(json.dumps(bde.build_extra(), ensure_ascii=False)) == SAVED
