"""원본(행정동 추정매출 CSV 여러 개)에서 region_map.csv의 행정동만 남겨 data/sales_areas.csv로 저장한다.

원본: 서울 열린데이터광장 OA-22175 '서울시 상권분석서비스(추정매출-행정동)'
- 공식 파일: 2021~2025년 연도별 zip ('파일내려받기')
- 2026년 분기: 공식 파일이 아직 없어 Sheet 화면의 CSV 내려받기(2025Q1~2026Q2)를 씀
원본은 calc_engine/raw/ 에 둔다 (git 제외).

사용법 (앞에 준 파일이 우선. 공식 파일을 먼저, Sheet 파일을 마지막에):
  python calc_engine/scripts/build_dataset.py calc_engine/raw/sales_dong_202?.csv calc_engine/raw/sales_dong_sheet_2025Q1_2026Q2.csv

같은 (분기, 행정동 코드, 업종 코드)가 여러 파일에 있으면 숫자가 모두 같은지 확인하고, 다르면 멈춘다.
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
KEY = ["기준_년분기_코드", "행정동_코드", "서비스_업종_코드"]
region_map = pd.read_csv(ROOT / "data" / "region_map.csv", dtype=str)

frames = []
for order, path in enumerate(sys.argv[1:]):
    df = pd.read_csv(path, encoding="cp949", dtype={"기준_년분기_코드": str, "행정동_코드": str})
    df = df[df["행정동_코드"].isin(region_map["행정동_코드"])].copy()
    df["_order"] = order
    frames.append(df)
    print(f"{Path(path).name}: 매핑 동 {len(df)}행, 분기 {df['기준_년분기_코드'].min()}~{df['기준_년분기_코드'].max()}")
raw = pd.concat(frames, ignore_index=True)

numeric = [c for c in raw.columns if c.endswith(("_금액", "_건수"))]
dup = raw[raw.duplicated(KEY, keep=False)]
if len(dup):
    spread = dup.groupby(KEY)[numeric].nunique().max(axis=1)
    if (spread > 1).any():
        sys.exit(f"여러 파일에서 숫자가 다른 행이 있습니다: {spread[spread > 1].index[:5].tolist()}")
    print(f"겹친 행 {len(dup)}개: 숫자가 모두 같음 → 앞 파일(공식 파일) 행을 씀")
raw = raw.sort_values("_order").drop_duplicates(KEY, keep="first").drop(columns="_order")

# 동 이름은 매핑표 기준 (Sheet 내려받기는 '·'가 '?'로 깨지는 경우가 있음)
raw["행정동_코드_명"] = raw["행정동_코드"].map(dict(zip(region_map["행정동_코드"], region_map["행정동_코드_명"])))
out = raw.merge(region_map[["지역", "행정동_코드"]], on="행정동_코드", how="inner")
cols = ["지역"] + [c for c in frames[0].columns if c != "_order"]
out = out[cols].sort_values(["기준_년분기_코드", "지역", "행정동_코드", "서비스_업종_코드"])

missing = set(region_map["행정동_코드"]) - set(out["행정동_코드"])
if missing:
    sys.exit(f"원본에 없는 행정동 코드: {missing}")

out.to_csv(ROOT / "data" / "sales_areas.csv", index=False, encoding="utf-8-sig")
print(f"{len(out)}행 저장, 분기 {out['기준_년분기_코드'].min()}~{out['기준_년분기_코드'].max()}")
