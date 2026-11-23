"""구성비(비중) 질문: 주말·요일·시간대·연령·성별 매출 비중과 점포 비율(폐업률·개업률·프랜차이즈 비율).

계산은 C 엔진의 `ratio`가 한다 (docs/CALC_API_v1.1.md). 여기서는 질문 속 표현이 어느 컬럼을 뜻하는지만 정한다.
"""
import re
from dataclasses import dataclass

# (컬럼 -> 사람이 읽는 이름). 순서가 곧 화면에 보여 주는 순서다.
TIME_BANDS = {
    "time_00_06_sales": ("새벽", "0~6시"), "time_06_11_sales": ("아침", "6~11시"),
    "time_11_14_sales": ("점심", "11~14시"), "time_14_17_sales": ("오후", "14~17시"),
    "time_17_21_sales": ("저녁", "17~21시"), "time_21_24_sales": ("밤", "21~24시"),
}
AGES = {"age_10_sales": "10대", "age_20_sales": "20대", "age_30_sales": "30대", "age_40_sales": "40대",
        "age_50_sales": "50대", "age_60_plus_sales": "60대 이상"}
DAYS = {"mon_sales": "월요일", "tue_sales": "화요일", "wed_sales": "수요일", "thu_sales": "목요일",
        "fri_sales": "금요일", "sat_sales": "토요일", "sun_sales": "일요일"}
GENDERS = {"male_sales": "남성", "female_sales": "여성"}
WEEK = {"weekday_sales": "평일", "weekend_sales": "주말"}
# 점포 비율: 개업(폐업) 수 ÷ 전체 점포 수 (C 엔진 DENOMINATORS['store'])
STORE_RATIOS = {"close_count": ("폐업률", "기간 폐업률"), "open_count": ("개업률", "기간 개업률"),
                "franchise_count": ("프랜차이즈 비율", "프랜차이즈 점포 비율"),
                "general_store_count": ("일반 점포 비율", "일반 점포 비율")}

GROUPS = {"time": TIME_BANDS, "age": AGES, "day": DAYS, "gender": GENDERS, "week": WEEK}
RATIO_COLUMNS = {*TIME_BANDS, *AGES, *DAYS, *GENDERS, *WEEK, *STORE_RATIOS}
GROUP_NAME = {"time": "시간대별", "age": "연령대별", "day": "요일별", "gender": "성별", "week": "평일·주말"}


def item_label(col: str) -> str:
    """목록 한 줄의 이름 (예: '저녁(17~21시)', '20대', '월요일')."""
    if col in TIME_BANDS:
        name, span = TIME_BANDS[col]
        return f"{name}({span})"
    for g in (AGES, DAYS, GENDERS, WEEK):
        if col in g:
            return g[col]
    return STORE_RATIOS.get(col, (col, col))[0]


def ratio_short(col: str) -> str:
    """목록 값 앞의 짧은 이름 (예: '주말 비중', '폐업률')."""
    if col in STORE_RATIOS:
        return STORE_RATIOS[col][0]
    if col in TIME_BANDS:
        return f"{TIME_BANDS[col][0]} 비중"
    for g in (AGES, DAYS, GENDERS, WEEK):
        if col in g:
            return f"{g[col]} 비중"
    return f"{col} 비중"


def ratio_full(col: str) -> str:
    """제목·결론에 쓰는 이름 (예: '주말 매출 비중', '기간 폐업률')."""
    if col in STORE_RATIOS:
        return STORE_RATIOS[col][1]
    return f"{item_label(col)} 매출 비중"


@dataclass
class Composition:
    columns: list[str]
    ratio: bool  # True=구성비(%), False=금액 합계
    distribution: bool = False  # 한 곳의 분포를 묻는 질문 (언제·연령대·요일·성별)
    group: str | None = None
    store: bool = False  # 점포 비율(폐업률 등)
    note: str | None = None  # 답변에 밝힐 해석 (예: 젊은층=20·30대)


_RATIO_WORDS = ("비중", "비율", "퍼센트", "%", "률", "율")
_AMOUNT_WORDS = ("매출", "금액", "얼마", "규모")

_TIME_TERMS = (("새벽", "time_00_06_sales"), ("심야", "time_00_06_sales"), ("아침", "time_06_11_sales"),
               ("오전", "time_06_11_sales"), ("출근", "time_06_11_sales"), ("점심", "time_11_14_sales"),
               ("런치", "time_11_14_sales"), ("오후", "time_14_17_sales"), ("낮 시간", "time_14_17_sales"),
               ("저녁", "time_17_21_sales"), ("퇴근", "time_17_21_sales"), ("야간", "time_21_24_sales"),
               ("밤", "time_21_24_sales"))
_DAY_TERMS = tuple((name, col) for col, name in DAYS.items())
_GENDER_TERMS = (("남성", "male_sales"), ("남자", "male_sales"), ("여성", "female_sales"), ("여자", "female_sales"))
_WEEK_TERMS = (("주말", "weekend_sales"), ("평일", "weekday_sales"), ("주중", "weekday_sales"))
_STORE_TERMS = (("폐업률", "close_count"), ("폐업율", "close_count"), ("폐업 비율", "close_count"),
                ("개업률", "open_count"), ("개업율", "open_count"), ("개업 비율", "open_count"),
                ("프랜차이즈 비율", "franchise_count"), ("프랜차이즈 비중", "franchise_count"),
                ("일반 점포 비율", "general_store_count"))
_AGE_RE = re.compile(r"(?<!\d)([1-9])0\s*대")
_AGE_2030 = re.compile(r"(?<!\d)20\s*[·~\-,]?\s*30\s*대?(?!\d|년)")
_YOUNG = ("젊은", "청년", "MZ")
_SENIOR = ("시니어", "어르신", "노년")

_DIST_TIME = ("시간대", "시간별", "몇 시", "몇시")
_DIST_TIME_WITH = ("매출", "몰", "붐", "손님", "장사", "바쁘", "피크")  # "언제" 가 이 말과 함께 나올 때만
_DIST_AGE = ("연령", "나이", "세대", "손님층", "고객층", "어떤 손님", "누가 와", "몇 대")
_DIST_WEEK = ("주말과 평일", "평일과 주말", "주중과 주말", "주말 vs 평일", "평일 vs 주말", "주말이랑 평일", "평일이랑 주말")


def _age_columns(q: str) -> list[str]:
    cols: list[str] = []
    for m in _AGE_RE.finditer(q):
        d = int(m.group(1)) * 10
        col = "age_60_plus_sales" if d >= 60 else f"age_{d}_sales"
        if col not in cols:
            cols.append(col)
    if _AGE_2030.search(q):
        cols = [c for c in cols if c not in ("age_20_sales", "age_30_sales")] + ["age_20_sales", "age_30_sales"]
    return cols


def detect_composition(q: str, available: set[str]) -> Composition | None:
    """질문에서 비중·구성 질문을 찾는다. 없으면 None. 데이터셋에 없는 컬럼은 버린다."""

    def keep(cols: list[str]) -> list[str]:
        return [c for c in dict.fromkeys(cols) if c in available]

    has_ratio = any(w in q for w in _RATIO_WORDS)
    has_amount = any(w in q for w in _AMOUNT_WORDS)

    for term, col in _STORE_TERMS:  # 폐업률·개업률·프랜차이즈 비율
        if term in q and col in available:
            return Composition([col], ratio=True, store=True)

    # 한 곳의 분포: 시간대·연령대·요일·성별·평일 vs 주말
    group = None
    if any(w in q for w in _DIST_TIME) or ("언제" in q and any(w in q for w in _DIST_TIME_WITH)):
        group = "time"
    elif any(w in q for w in _DIST_AGE):
        group = "age"
    elif "요일" in q:
        group = "day"
    elif "성별" in q or "남녀" in q:
        group = "gender"
    elif any(w in q for w in _DIST_WEEK):
        group = "week"
    if group:
        cols = keep(list(GROUPS[group]))
        if cols:
            return Composition(cols, ratio=True, distribution=True, group=group)

    # 특정 대상: 주말·평일·요일·시간대·연령·성별
    cols: list[str] = []
    note = None
    ages = _age_columns(q)
    if ages:
        cols += ages
        if len(ages) > 1:
            note = f"{' · '.join(AGES[a] for a in ages)}을 함께 보여 드리고, 순위는 {AGES[ages[0]]} 기준입니다."
    if any(w in q for w in _YOUNG) and not ages:
        cols += ["age_20_sales", "age_30_sales"]
        note = "젊은층은 20·30대로 봤습니다. 순위는 20대 기준이고 30대를 함께 보여 드립니다."
    if any(w in q for w in _SENIOR) and not ages:
        cols += ["age_60_plus_sales"]
        note = "시니어·어르신은 60대 이상으로 봤습니다."
    for terms in (_DAY_TERMS, _GENDER_TERMS, _WEEK_TERMS, _TIME_TERMS):
        for term, col in terms:
            if term in q:
                cols.append(col)
                break  # 같은 묶음에서는 처음 맞은 것 하나
    cols = keep(cols)
    if not cols:
        return None
    # 비중 말이 있으면 구성비, "매출" 같은 금액 말만 있으면 금액 합계, 둘 다 없으면 구성비("저녁 장사 강한 곳")
    return Composition(cols, ratio=has_ratio or not has_amount, note=note)
