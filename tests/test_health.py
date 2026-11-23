from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body

def test_health_reports_supported_regions_for_dashboard():
    """대시보드는 /health 의 regions 로 어느 지역 질문을 서버로 보낼지 정한다 (이름은 area_map.csv 의 area_name)."""
    import csv

    regions = client.get("/health").json()["regions"]
    with open("data/area_map.csv", encoding="utf-8-sig", newline="") as f:
        expected = list(dict.fromkeys(row["area_name"] for row in csv.DictReader(f)))
    assert regions == expected and len(regions) == 20
    assert {"제기동", "명동", "종로1~4가", "성수"} <= set(regions)
