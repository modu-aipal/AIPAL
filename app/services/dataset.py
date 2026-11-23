"""기본 데이터셋 메타데이터. C 엔진 실제 데이터 기준 (docs/DATA.md, docs/CALC_API_v1.1.md).

컬럼 구조만 정의하며 실제 수치는 없다. 지역 목록과 식별값은 data/area_map.csv 에서 읽는다.
"""
from app.schemas.plan import ColumnMeta, DatasetMeta
from app.services.areas import load_areas

AREA_IDS = load_areas()  # area_name -> area_id (대시보드 id와 같음)
REGIONS = list(AREA_IDS)  # 지원 지역 20곳 (엔진이 받는 이름)

# 업종 묶음 이름: B는 이름만 전달하고 실제 업종으로의 펼침은 C 엔진이 수행 (DATA.md 4절, 팀 검토 필요)
INDUSTRY_GROUPS = ["카페", "음식점", "주점", "편의점", "소매", "의류", "미용"]

# 실제 업종 62종 (서비스_업종_코드_명)
REAL_INDUSTRIES = [
    "PC방", "가구", "가방", "가전제품", "가전제품수리", "고시원", "골프연습장", "네일숍", "노래방", "당구장",
    "문구", "미곡판매", "미용실", "반찬가게", "분식전문점", "서적", "섬유제품", "세탁소", "수산물판매", "슈퍼마켓",
    "스포츠 강습", "스포츠클럽", "시계및귀금속", "신발", "안경", "애완동물", "양식음식점", "여관", "예술학원", "완구",
    "외국어학원", "운동/경기용품", "육류판매", "의료기기", "의약품", "인테리어", "일반교습학원", "일반의류", "일반의원",
    "일식음식점", "자동차미용", "자동차수리", "자전거 및 기타운송장비", "전자상거래업", "제과점", "조명용품",
    "중식음식점", "철물점", "청과상", "치과의원", "치킨전문점", "커피-음료", "컴퓨터및주변장치판매", "패스트푸드점",
    "편의점", "피부관리실", "한식음식점", "한의원", "핸드폰", "호프-간이주점", "화장품", "화초",
]
INDUSTRIES = list(dict.fromkeys([*INDUSTRY_GROUPS, *REAL_INDUSTRIES]))  # 묶음 + 실제 업종 (중복 제거)

# 질문 속 표현 -> 업종 값 (대상 값이 허용값에 있을 때만 사용)
INDUSTRY_ALIASES = {
    "커피전문점": "카페", "커피숍": "카페", "커피": "카페",
    "식당": "음식점", "레스토랑": "음식점",
    "술집": "주점", "호프": "주점", "이자카야": "주점",
    "소매점": "소매", "옷가게": "의류", "헤어샵": "미용",
}


def area_ids(regions: list[str]) -> str:
    """단일 지역이면 식별값, 복수면 쉼표 연결(임시안), 없으면 빈 문자열."""
    return ",".join(AREA_IDS[r] for r in regions if r in AREA_IDS)


def default_dataset() -> DatasetMeta:
    num = lambda n: ColumnMeta(name=n, dtype="number", role="measure")  # noqa: E731
    return DatasetMeta(
        columns=[
            ColumnMeta(name="region", dtype="string", role="dimension", allowed_values=REGIONS),
            ColumnMeta(name="industry", dtype="string", role="dimension", allowed_values=INDUSTRIES),
            ColumnMeta(name="quarter", dtype="date", role="dimension"),  # 분기 단위 (예: 2025Q4)
            num("est_sales"), num("est_count"),
            num("weekday_sales"), num("weekend_sales"),
            num("male_sales"), num("female_sales"),
            # 요일·시간대·연령대 매출: 구성비(ratio) 질문에 쓴다 (C 엔진 MEASURES 와 같은 이름)
            *[num(f"{d}_sales") for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")],
            *[num(f"time_{b}_sales") for b in ("00_06", "06_11", "11_14", "14_17", "17_21", "21_24")],
            *[num(f"age_{a}_sales") for a in ("10", "20", "30", "40", "50", "60_plus")],
            # 점포 지표 (OA-22172). 점포 수는 프랜차이즈를 포함한 전체
            num("store_count"), num("general_store_count"), num("franchise_count"),
            num("open_count"), num("close_count"),
        ]
    )
