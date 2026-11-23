"""C 계산 엔진의 데이터: CSV 읽기·검사, API 컬럼 카탈로그, 업종 묶음 매핑.

데이터 정의와 근거는 docs/DATA.md 참고.
"""
from io import StringIO
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DEFAULT_DATA = HERE / "data" / "sales_areas.csv"
STORE_DATA = HERE / "data" / "stores_areas.csv"
REGION_MAP = HERE / "data" / "region_map.csv"

DATASET_ID = "commercial_area_v1"
DATA_SOURCE = ("서울 열린데이터광장 OA-22175 「서울시 상권분석서비스(추정매출-행정동)」, "
               "OA-22172 「서울시 상권분석서비스(점포-행정동)」 (서울특별시·서울신용보증재단)")
DATA_VERSION = ("OA-22175·OA-22172 2021Q1~2026Q2 (2021~2025 공식 파일 + 2026Q1·Q2 Sheet 내려받기, "
                "추정매출 2026-11-19·점포 2026-11-23 받음)")

REQUIRED = ["기준_년분기_코드", "행정동_코드", "행정동_코드_명", "서비스_업종_코드_명", "당월_매출_금액"]
TEXT_COLUMNS = {"지역", "기준_년분기_코드", "행정동_코드", "행정동_코드_명", "서비스_업종_코드", "서비스_업종_코드_명"}


class DataError(Exception):
    """사용자에게 그대로 보여 줄 데이터 오류."""


def load_sales_csv(source) -> pd.DataFrame:
    """파일 경로나 파일 객체를 읽어 검사한다. UTF-8/CP949, 서울시 원본(지역 열 없음)도 받는다."""
    raw = source.read_bytes() if isinstance(source, Path) else source.read()
    if not raw.strip():
        raise DataError("빈 파일입니다.")
    for encoding in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise DataError("파일 인코딩을 읽을 수 없습니다. UTF-8 또는 CP949 CSV만 지원합니다.")
    try:
        df = pd.read_csv(StringIO(text), dtype=str)
    except pd.errors.ParserError:
        raise DataError("CSV 형식이 아닙니다.")
    if df.empty:
        raise DataError("데이터 행이 없습니다.")
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise DataError(f"필수 컬럼이 없습니다: {', '.join(missing)}")
    for col in df.columns:
        if col in TEXT_COLUMNS:
            continue
        numbers = pd.to_numeric(df[col], errors="coerce")
        bad = numbers.isna() | df[col].isna()
        if bad.any():
            row = int(bad.idxmax()) + 2  # 머리글 1행 + 0부터 세는 번호
            raise DataError(f"'{col}' 컬럼에 숫자가 아니거나 빈 값이 있습니다 ({row}행).")
        df[col] = numbers.astype("int64")
    if "지역" not in df.columns:
        # 서울시 원본: 매핑표의 행정동만 남긴다 (이름이 같은 동이 있으므로 코드로 합침)
        region_map = pd.read_csv(REGION_MAP, dtype=str)[["지역", "행정동_코드"]]
        df = df.merge(region_map, on="행정동_코드", how="inner")
        if df.empty:
            raise DataError("지원하는 지역(region_map.csv)의 행정동이 파일에 없습니다.")
        df = df[["지역"] + [c for c in df.columns if c != "지역"]]
    return df


# ---- API 컬럼 카탈로그 (요청·응답에서 쓰는 이름 → 원본 컬럼) ----
# 차원: 묶기·필터에 쓰는 글자 컬럼. year_month는 v1.0 호환용 별칭(데이터는 분기 단위라 분기로 묶음)
DIMENSIONS = {"region": "지역", "dong": "행정동_코드_명", "industry": "서비스_업종_코드_명", "quarter": "기준_년분기_코드"}
TIME_ALIASES = {"year_month": "quarter"}

_DAYS = {"mon": "월", "tue": "화", "wed": "수", "thu": "목", "fri": "금", "sat": "토", "sun": "일"}
_BANDS = ["00_06", "06_11", "11_14", "14_17", "17_21", "21_24"]
_AGES = {"10": "10", "20": "20", "30": "30", "40": "40", "50": "50", "60_plus": "60_이상"}

# 측정값: 이름 → (원본 컬럼, ratio 분모 묶음)
MEASURES = {
    "est_sales": ("당월_매출_금액", "sales"),
    "est_count": ("당월_매출_건수", "count"),
    "weekday_sales": ("주중_매출_금액", "sales"),
    "weekend_sales": ("주말_매출_금액", "sales"),
    **{f"{k}_sales": (f"{v}요일_매출_금액", "sales") for k, v in _DAYS.items()},
    **{f"time_{b}_sales": (f"시간대_{b.replace('_', '~')}_매출_금액", "sales") for b in _BANDS},
    "male_sales": ("남성_매출_금액", "gender"),
    "female_sales": ("여성_매출_금액", "gender"),
    **{f"age_{k}_sales": (f"연령대_{v}_매출_금액", "age") for k, v in _AGES.items()},
}
# ratio 분모: 성별·연령은 법인 매출(성별·연령 정보 없음)이 빠져 있어 총매출이 아니라 각 합계로 나눈다
DENOMINATORS = {
    "sales": ["당월_매출_금액"],
    "count": ["당월_매출_건수"],
    "gender": ["남성_매출_금액", "여성_매출_금액"],
    "age": [MEASURES[f"age_{k}_sales"][0] for k in _AGES],
    "store": ["전체_점포_수"],
}
UNAVAILABLE: dict[str, str] = {}

# ---- 점포 데이터 (OA-22172) ----
# 공식 파일의 '점포_수'는 프랜차이즈를 뺀 일반 점포, '유사_업종_점포_수'가 전체 점포.
# 가공 파일은 Sheet 쪽 이름(일반_점포_수, 전체_점포_수)으로 통일했다 (scripts/build_store_dataset.py).
STORE_MEASURES = {
    "store_count": ("전체_점포_수", "store"),
    "general_store_count": ("일반_점포_수", "store"),
    "franchise_count": ("프랜차이즈_점포_수", "store"),
    "open_count": ("개업_점포_수", "store"),
    "close_count": ("폐업_점포_수", "store"),
}
MEASURES.update(STORE_MEASURES)


def table_of(family: str) -> str:
    """지표 묶음이 들어 있는 표: 점포 묶음은 stores, 나머지는 sales"""
    return "stores" if family == "store" else "sales"


def load_store_csv(path: Path = STORE_DATA) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"기준_년분기_코드": str, "행정동_코드": str, "서비스_업종_코드": str})
    for col, _ in STORE_MEASURES.values():
        df[col] = df[col].astype("int64")
    return df


def industry_groups(df: pd.DataFrame) -> dict[str, list[str]]:
    """업종 묶음 이름 → 실제 업종 이름 목록 (C 제안, docs/DATA.md). 코드 체계: CS1 외식, CS2 서비스, CS3 소매."""
    codes = df[["서비스_업종_코드", "서비스_업종_코드_명"]].drop_duplicates()
    by_code = dict(zip(codes["서비스_업종_코드"], codes["서비스_업종_코드_명"]))
    pick = lambda *cs: [by_code[c] for c in cs if c in by_code]  # noqa: E731
    return {
        "카페": pick("CS100010"),
        "음식점": pick(*[f"CS1000{i:02d}" for i in range(1, 9)]),  # 한식·중식·일식·양식·제과·패스트푸드·치킨·분식
        "주점": pick("CS100009"),
        "편의점": pick("CS300002"),
        "소매": sorted(n for c, n in by_code.items() if c.startswith("CS3")),
        "의류": pick("CS300011"),
        "미용": pick("CS200028", "CS200029", "CS200030"),  # 미용실·네일숍·피부관리실
    }
