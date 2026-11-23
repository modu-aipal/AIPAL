"""대시보드 상가 검색용 파일 만들기: 소상공인시장진흥공단 상가(상권)정보 → dashboard/stores/{area_id}.json

원본: 공공데이터포털 「소상공인시장진흥공단_상가(상권)정보」 (data.go.kr 15083033, 분기 갱신, 이용 제한 없음)
      내려받은 zip 안의 서울 파일(UTF-8 CSV)을 넣는다. 원본은 크기(서울 약 300MB) 때문에 git에 넣지 않는다.

사용법: python data/build_stores.py <상가(상권)정보_서울_YYYYMM.csv> <기준일 YYYY-MM-DD>
대시보드 20곳과 행정동의 대응은 data/area_map.csv 의 dong_code(행정동 코드)로 맞춘다.
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dashboard" / "stores"
SOURCE = "소상공인시장진흥공단 상가(상권)정보 (공공데이터포털 15083033)"
# 한 행 = [상호, 업종(cats 번호), 층, 건물, 도로명주소(서울특별시 생략), 동(dongs 번호), 경도, 위도]
# 업종은 cats 에 [대분류, 중분류, 소분류]로 한 번씩만 적고 번호로 가리킨다 (파일 크기 줄이기)
COLS = ["상호", "업종", "층", "건물", "도로명주소", "동", "경도", "위도"]


def main(src: str, asof: str) -> None:
    with open(ROOT / "data" / "area_map.csv", encoding="utf-8-sig", newline="") as f:
        dong_area = {r["dong_code"]: r["area_id"] for r in csv.DictReader(f)}
    rows = defaultdict(list)
    dongs = defaultdict(list)
    cats = defaultdict(list)
    with open(src, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            area = dong_area.get(r["행정동코드"])
            if not area:
                continue
            if r["행정동명"] not in dongs[area]:
                dongs[area].append(r["행정동명"])
            name = r["상호명"] + (f" {r['지점명']}" if r["지점명"] else "")
            road = r["도로명주소"].removeprefix("서울특별시 ")
            cat = [r["상권업종대분류명"], r["상권업종중분류명"], r["상권업종소분류명"]]
            if cat not in cats[area]:
                cats[area].append(cat)
            rows[area].append([
                name, cats[area].index(cat), r["층정보"], r["건물명"],
                road, dongs[area].index(r["행정동명"]), round(float(r["경도"]), 6), round(float(r["위도"]), 6),
            ])
    missing = set(dong_area.values()) - set(rows)
    if missing:
        sys.exit(f"가게가 하나도 없는 상권: {sorted(missing)} (행정동 코드가 바뀌었는지 확인)")
    OUT.mkdir(exist_ok=True)
    for area, rs in sorted(rows.items()):
        rs.sort(key=lambda x: (cats[area][x[1]], x[0]))
        doc = {"area": area, "source": SOURCE, "asof": asof, "dongs": dongs[area], "cats": cats[area],
               "cols": COLS, "rows": rs}
        path = OUT / f"{area}.json"
        path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"{area}: {len(rs)}곳, {path.stat().st_size // 1024}KB")
    print(f"합계 {sum(map(len, rows.values()))}곳")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
