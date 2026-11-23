"""점포 원본(행정동별 업종별 점포 CSV 여러 개)에서 region_map.csv의 행정동만 남겨 data/stores_5regions.csv로 저장한다.

원본: 서울 열린데이터광장 OA-22172 '서울시 상권분석서비스(점포-행정동)'
- 공식 파일: 2021~2025년 연도별 zip ('파일내려받기')
- 2026년 분기: Sheet 화면의 CSV 내려받기(화면 기본 조건 그대로, 2025Q1~2026Q2)
원본은 calc_engine/raw/ 에 둔다 (git 제외).

컬럼 이름 주의: 공식 파일의 '점포_수'는 프랜차이즈를 뺀 일반 점포, '유사_업종_점포_수'가 전체 점포다.
Sheet 파일은 같은 값을 '일반_점포_수', '전체_점포_수'로 부른다 (2025년 141,218행 전 칸 대조로 확인).
가공 파일은 오해가 없는 Sheet 쪽 이름으로 통일한다.

사용법 (앞에 준 파일이 우선. 공식 파일을 먼저, Sheet 파일을 마지막에):
  python calc_engine/scripts/build_store_dataset.py calc_engine/raw/store_dong_202?.csv calc_engine/raw/store_dong_sheet.csv
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
KEY = ["기준_년분기_코드", "행정동_코드", "서비스_업종_코드"]
RENAME = {"점포_수": "일반_점포_수", "유사_업종_점포_수": "전체_점포_수"}
COLUMNS = KEY[:1] + ["행정동_코드", "행정동_코드_명", "서비스_업종_코드", "서비스_업종_코드_명",
                     "전체_점포_수", "일반_점포_수", "프랜차이즈_점포_수", "개업_점포_수", "개업_율", "폐업_점포_수", "폐업_률"]
NUMERIC = COLUMNS[5:]
region_map = pd.read_csv(ROOT / "data" / "region_map.csv", dtype=str)

frames = []
for order, path in enumerate(sys.argv[1:]):
    df = pd.read_csv(path, encoding="cp949", dtype={"기준_년분기_코드": str, "행정동_코드": str})
    if "유사_업종_점포_수" in df.columns:
        df = df.rename(columns=RENAME)
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        sys.exit(f"{Path(path).name}: 컬럼이 없습니다 {missing}")
    if not (df["전체_점포_수"].astype(int) == df["일반_점포_수"].astype(int) + df["프랜차이즈_점포_수"].astype(int)).all():
        sys.exit(f"{Path(path).name}: 전체 = 일반 + 프랜차이즈 관계가 맞지 않는 행이 있습니다")
    df = df[df["행정동_코드"].isin(region_map["행정동_코드"])][COLUMNS].copy()
    df["_order"] = order
    frames.append(df)
    print(f"{Path(path).name}: 8개 동 {len(df)}행, 분기 {df['기준_년분기_코드'].min()}~{df['기준_년분기_코드'].max()}")
raw = pd.concat(frames, ignore_index=True)
for c in NUMERIC:
    raw[c] = pd.to_numeric(raw[c]).astype("int64")

dup = raw[raw.duplicated(KEY, keep=False)]
if len(dup):
    spread = dup.groupby(KEY)[NUMERIC].nunique().max(axis=1)
    if (spread > 1).any():
        sys.exit(f"여러 파일에서 숫자가 다른 행이 있습니다: {spread[spread > 1].index[:5].tolist()}")
    print(f"겹친 행 {len(dup)}개: 숫자가 모두 같음 → 앞 파일(공식 파일) 행을 씀")
raw = raw.sort_values("_order").drop_duplicates(KEY, keep="first").drop(columns="_order")

# 동 이름은 매핑표 기준 (Sheet 내려받기는 '·'가 '?'로 깨지는 경우가 있음)
raw["행정동_코드_명"] = raw["행정동_코드"].map(dict(zip(region_map["행정동_코드"], region_map["행정동_코드_명"])))
out = raw.merge(region_map[["지역", "행정동_코드"]], on="행정동_코드", how="inner")
out = out[["지역"] + COLUMNS].sort_values(["기준_년분기_코드", "지역", "행정동_코드", "서비스_업종_코드"])

missing = set(region_map["행정동_코드"]) - set(out["행정동_코드"])
if missing:
    sys.exit(f"원본에 없는 행정동 코드: {missing}")

out.to_csv(ROOT / "data" / "stores_5regions.csv", index=False, encoding="utf-8-sig")
print(f"{len(out)}행 저장, 분기 {out['기준_년분기_코드'].min()}~{out['기준_년분기_코드'].max()}")
