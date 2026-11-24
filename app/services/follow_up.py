"""이어 묻기: "그럼 홍대는?"처럼 앞 질문의 조건(지역·업종·기간·지표)을 이어받아야 하는 질문.

서버는 대화를 저장하지 않는다. 대시보드가 직전 질문 몇 개(history)를 같이 보내면, 그 질문들을 같은 규칙으로 다시
읽어 마지막 계획의 조건만 꺼낸다 (모델 호출 없음, 질문 원문은 저장하지 않는다).

이어받는 조건 (모두 만족할 때만): ① 이어 묻는 표현이 있고 ② 새 질문에 그 조건이 빠져 있고
③ 그 질문 유형이 그 조건을 필요로 한다. 애매하면 이어받지 않고 되묻는다 (엉뚱한 조건이 붙는 것보다 안전).
"""
import re
from dataclasses import dataclass, field

from app.schemas.plan import MetricSpec, PeriodSpec

MAX_HISTORY = 3
MAX_HISTORY_CHARS = 200

# 앞 질문을 가리키는 말
_CUES = ("그럼", "그러면", "그렇다면", "이번엔", "이번에는", "거기", "그곳", "그 지역", "그쪽", "같은 기간", "같은 업종",
         "같은 조건", "같은 지역", "다시", "아니면", "그 업종", "그건", "그것은", "그것도")
# 짧게 끝나는 생략형: "홍대는?", "작년은?", "점포당은?", "강남도?"
_ELLIPSIS = re.compile(r"(?:는|은|도|은요|는요|이랑|랑|하고)\s*[?？]?$")
_ELLIPSIS_MAX_CHARS = 14
_ELLIPSIS_MAX_TOKENS = 2  # "홍대는?", "작년 4분기는?"까지. "요즘 뜨는 상권은?"처럼 내용이 있는 질문은 새 질문이다


@dataclass
class PlanContext:
    """직전에 성공한 계획에서 이어받을 조건."""

    regions: list[str] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)
    period: PeriodSpec | None = None  # 질문에 명시했거나 '작년·최근 N분기'처럼 말한 기간만 (기본값으로 정한 기간은 아님)
    metrics: list[MetricSpec] = field(default_factory=list)
    intent: str = ""


def is_follow_up(question: str) -> bool:
    q = question.strip()
    if any(c in q for c in _CUES):
        return True
    return len(q) <= _ELLIPSIS_MAX_CHARS and len(q.split()) <= _ELLIPSIS_MAX_TOKENS and bool(_ELLIPSIS.search(q))


def eul_reul(word: str) -> str:
    """받침 유무로 을/를."""
    ch = word.strip()[-1:] if word.strip() else ""
    if "가" <= ch <= "힣":
        return word + ("을" if (ord(ch) - 0xAC00) % 28 else "를")
    return word + "을(를)"


def clean_history(history: list[str] | None) -> list[str]:
    """대시보드가 보낸 직전 질문 목록을 안전하게 줄인다: 문자열만, 빈 것 제외, 각 200자, 최근 3개."""
    out = [h.strip()[:MAX_HISTORY_CHARS] for h in (history or []) if isinstance(h, str) and h.strip()]
    return out[-MAX_HISTORY:]
