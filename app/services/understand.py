"""질문의 의미 해석: 개념(concept) · 방향(direction) · 개수(top_n).

사람은 "잘나가는", "뜨는", "돈 되는"처럼 말한다. 이 표현이 데이터의 어떤 지표를 뜻하는지 정한다.
- explicit: 지표를 직접 말한 단어(성장·증가, 점포당). 가장 확실해서 항상 우선한다.
- model  : 모델(펄이)이 질문 전체를 보고 고른 개념. 목록에 없는 표현을 이해한다.
- idiom  : 코드에 적어 둔 알려진 관용 표현. 모델이 못 끝냈을 때의 안전망이다.
우선순위(CONCEPT_PRIORITY)는 설정으로 바꿀 수 있고, scripts/eval_planner.py 점수로 비교한다.
"""
import re

EXPLICIT_GROWTH = ("성장", "증가", "증감", "감소", "상승", "하락", "늘어", "줄어")
IDIOM_GROWTH = ("뜨는", "뜨고", "핫", "떠오르", "오르는", "급상승", "상승세")
IDIOM_OVERALL = ("잘나가", "잘 나가", "잘되", "잘 되", "잘돼", "잘 돼", "잘팔", "잘 팔", "인기", "돈 되", "돈이 되",
                 "돈 벌", "돈벌", "장사 어때", "장사가 어때", "장사 잘", "장사잘", "경기 어때", "괜찮은 업종")
IDIOM_EFFICIENCY = ("얼마나 벌", "얼마 벌", "한 달에 얼마", "월에 얼마")
IDIOM_COUNT = ("몇 개", "몇개", "몇 곳", "몇곳", "몇 군데", "몇군데")
SIZE_WORDS = ("매출 높", "매출이 높", "매출 큰", "매출이 큰", "매출 많", "매출이 많", "규모", "제일 큰", "가장 큰")
LOW_WORDS = ("블루오션", "한산", "안 되", "안되", "안 돼", "안돼", "안 팔", "안팔", "못 나가", "못나가", "망하", "하위", "낮은", "적은",
             "꼴찌", "최저", "부진")
PLACE_NOUNS = ("곳", "동네", "상권", "지역", "데는", "어디", "어느")

_TOPN = re.compile(r"(?:TOP|top|Top|톱|상위|하위)\s*(\d{1,2})|(\d{1,2})\s*(?:개|곳|위|군데)")


def explicit_concept(q: str) -> str | None:
    if "점포당" in q:
        return "efficiency"
    if any(w in q for w in EXPLICIT_GROWTH):
        return "growth"
    return None


def idiom_concept(q: str) -> str | None:
    if any(w in q for w in IDIOM_EFFICIENCY):
        return "efficiency"
    if any(w in q for w in IDIOM_GROWTH):
        return "growth"
    if any(w in q for w in IDIOM_COUNT):
        return "count"
    if any(w in q for w in IDIOM_OVERALL):
        return "overall"
    if any(w in q for w in SIZE_WORDS):
        return "size"
    return None


def resolve_concept(q: str, model_concept: str | None, priority: str = "model_first") -> str | None:
    """explicit > (model, idiom) 순서는 priority 로 정한다. 없으면 None."""
    exp = explicit_concept(q)
    if exp:
        return exp
    mc = None if model_concept in (None, "none") else model_concept
    idi = idiom_concept(q)
    return (idi or mc) if priority == "rules_first" else (mc or idi)


HIGH_WORDS = ("높은", "많은", "큰 ", "제일", "가장", "최고", "최대", "상위", "TOP", "top", "많이")


def resolve_direction(q: str, model_direction: str | None) -> str:
    """'high' | 'low'. 낮은·안 되는·하위면 low, 높은·많은·제일이면 high, 둘 다 없을 때만 모델 값."""
    if any(w in q for w in LOW_WORDS):
        return "low"
    if any(w in q for w in HIGH_WORDS):
        return "high"
    return "low" if model_direction == "low" else "high"


def parse_top_n(q: str, model_top_n: int | None = None) -> int | None:
    m = _TOPN.search(q)
    n = int(m.group(1) or m.group(2)) if m else model_top_n
    return n if n and 1 <= n <= 20 else None


def has_place_noun(q: str) -> bool:
    return any(w in q for w in PLACE_NOUNS)


# ---- 입지 질문 ("의류는 어디서 장사하는 게 좋아?") 과 경쟁 질문 ----
_LOC_WHERE = ("어디서", "어디에서", "어디에", "어디가", "어디는", "어디로", "어느 동네", "어느 지역", "어느 상권",
              "어느 곳", "어느곳", "어디 ")
_LOC_ACTION = ("장사", "개원", "개업", "창업", "차리", "차릴", "열면", "열어", "오픈", "입점", "가게", "점포", "운영",
               "하는 게", "하는게", "하면", "하려면", "해야", "좋", "괜찮", "유리", "낫", "추천", "적합", "잘 될", "잘될")
COMPETITION_WORDS = ("경쟁", "포화", "레드오션", "블루오션", "너무 많은", "과밀", "몰려")


def is_location_question(q: str) -> bool:
    """'어디서 ~하는 게 좋아?'처럼 장소를 고르는 질문. 특정 지역의 가부 질문('성수에서 차리면 괜찮을까?')은 아니다."""
    return any(w in q for w in _LOC_WHERE) and any(w in q for w in _LOC_ACTION)


def is_competition_question(q: str) -> bool:
    return any(w in q for w in COMPETITION_WORDS)
