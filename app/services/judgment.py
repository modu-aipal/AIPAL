"""판단 표현("좋은 곳", "안정적인", "망하는", "전망", "투자처" …)을 데이터로 잴 수 있는 지표에 연결한다.

원칙: 판단 단어를 일괄 차단하지 않는다. 잴 수 있는 것은 지표로 바꿔 답하고(추천이 아닌 데이터 순위),
잴 수 없는 것(투자 수익, 성공 확률)만 이유와 함께 거절한다. 코드가 정하므로 모델이 지어낼 수 없다.

종류(kind) -> 지표
- startup  : 창업·입지 ("창업하기 좋은 곳", "열면 괜찮을까")  -> 점포 수 + 점포당 월평균 매출 + 증감
- survival : 안정·생존 ("안정적인", "살아남기 쉬운", "폐업 적은") -> 폐업률 낮은 순
- danger   : 폐업 위험 ("망하는", "폐업 많은")                    -> 폐업률 높은 순
- income   : 수입 ("얼마 벌어", "수입")                           -> 점포당 월평균 매출 (순이익 아님)
- outlook  : 전망 ("앞으로", "유망", "전망")                      -> 최근 추이·증감 (예측 아님)
- compare  : 선택 ("A랑 B 중 어디가 나아")                        -> 점포당 + 증감 비교
- invest   : 투자 ("투자처", "수익률")                            -> 거절
- success  : 성공 확률                                            -> 거절
"""
import re
from dataclasses import dataclass

INVEST_WORDS = ("투자", "수익률", "재테크", "시세 차익")
SUCCESS_WORDS = ("성공 확률", "성공확률", "성공할 확률", "성공 가능성", "성공할까")
_DANGER_RE = re.compile(r"(?<![유희])망(?:하는|할|한|했|해)")  # "유망한", "희망"은 제외
DANGER_WORDS = ("문 닫는", "문닫는", "위험한 업종", "위험한 상권", "폐업 많", "폐업이 많", "폐업 높", "폐업이 높")
SURVIVAL_WORDS = ("안정적", "안정된", "안정성", "살아남", "생존", "오래 가", "오래가", "망하지", "안 망", "폐업 적", "폐업이 적", "폐업 낮", "폐업이 낮")
OUTLOOK_WORDS = ("전망", "앞으로", "향후", "내년", "유망", "장래", "잘 될", "잘될", "뜰 업종", "뜰 상권")
INCOME_WORDS = ("얼마 벌", "얼마나 벌", "수입", "월급", "얼마 남", "벌어")
STARTUP_WORDS = ("창업", "차리면", "차려도", "차릴", "차리기", "열면", "열기", "열어도", "개업하", "괜찮", "좋을까", "어떨까",
                 "해볼만", "할 만한", "할만한", "하면 좋", "뭐 하면", "뭘 하면", "무엇을 하면", "추천", "적합", "시작하기")
COMPARE_CUES = ("나아", "낫", "더 좋", "좋아?", "유리")  # "더 잘돼?", "어디가 더 커?"는 기존 해석(규모) 유지
COMPARE_LINKS = ("중", "vs", "VS", "랑", "와 ", "과 ", "하고")

DISCLAIMERS = {
    "startup": "현재 데이터로 본 현황이며 창업 성공 여부나 추천이 아닙니다. 임대료·유동인구·권리금·경쟁 강도는 반영되지 않았어요.",
    "survival": "폐업률은 과거 기록이며 앞으로의 생존을 보장하지 않습니다. 점포 수가 너무 적은 곳은 비율이 크게 흔들려 제외했어요.",
    "danger": "폐업률은 과거 기록이며 앞으로의 폐업을 예측하지 않습니다. 점포 수가 너무 적은 곳은 비율이 크게 흔들려 제외했어요.",
    "income": "매출이며 수익(순이익)이 아닙니다. 임대료·인건비·재료비는 반영되지 않았어요.",
    "outlook": "과거 데이터의 추이이며 앞으로의 예측이 아닙니다.",
    "compare": "비교용 현황이며 어느 쪽을 추천하는 것이 아닙니다. 임대료·유동인구·권리금은 반영되지 않았어요.",
}
INVEST_REASON = "투자 판단이나 수익률은 제공하지 않아요. 대신 업종별 매출·폐업률 데이터를 볼 수 있어요."
SUCCESS_REASON = "추천·창업 성공 여부 판단은 지원하지 않습니다. 대신 데이터로 비교해 볼 수 있습니다."


@dataclass
class Judgment:
    kind: str
    direction: str | None = None  # 'low' | 'high' (정렬 방향이 정해지는 종류만)


def _has(q: str, words) -> bool:
    return any(w in q for w in words)


def detect_judgment(q: str, n_areas: int = 0, n_inds: int = 0) -> Judgment | None:
    """질문 속 판단 표현의 종류. 없으면 None. 우선순위: 거절 > 폐업 > 전망 > 수입 > 비교 > 창업."""
    if _has(q, INVEST_WORDS):
        return Judgment("invest")
    if _has(q, SUCCESS_WORDS):
        return Judgment("success")
    if _has(q, DANGER_WORDS) or _DANGER_RE.search(q):
        return Judgment("danger", "high")
    if _has(q, SURVIVAL_WORDS):
        return Judgment("survival", "low")
    if _has(q, OUTLOOK_WORDS):
        return Judgment("outlook")
    if _has(q, INCOME_WORDS):
        return Judgment("income")
    if (n_areas >= 2 or n_inds >= 2) and _has(q, COMPARE_CUES) and _has(q, COMPARE_LINKS):
        return Judgment("compare")
    if _has(q, STARTUP_WORDS):
        return Judgment("startup")
    return None
