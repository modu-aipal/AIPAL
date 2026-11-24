"""기간 해석: 명시된 분기, "최근·올해·작년" 같은 상대 표현, 질문 유형별 기본 기간.

데이터는 분기 단위이므로 기간은 분기 경계(YYYY-MM, 시작 1·4·7·10월 / 끝 3·6·9·12월)로 만든다.
"""
import re

from app.schemas.plan import PeriodSpec

Quarter = tuple[int, int]  # (연도, 분기 1~4)

_DATE_RE = re.compile(r"(\d{4})\s*년(?:\s*(\d{1,2})\s*월)?|(\d{4})-(\d{2})")
_Q_RANGE = re.compile(r"(\d{4})\s*년\s*([1-4])\s*(?:분기)?\s*[~\-]\s*([1-4])\s*분기")
_Q_ONE = re.compile(r"(\d{4})\s*년\s*([1-4])\s*분기")
_Q_CODE = re.compile(r"(\d{4})\s*-?\s*Q([1-4])", re.I)

_REL_YEARS = re.compile(r"(?:최근|지난|최신)\s*(\d+)\s*년")
_REL_QUARTERS = re.compile(r"(?:최근|지난|최신)\s*(\d+)\s*분기")
_REL_ONE_Q = re.compile(r"(?:최근|지난|최신|이번)\s*(?:한\s*)?분기")
_YEAR_Q = re.compile(r"(올해|금년|작년|지난해)\s*([1-4])(?:\s*분기)?(?:\s*[~\-]\s*([1-4]))?\s*분기")
_YEAR_HALF = re.compile(r"(올해|금년|작년|지난해)\s*(상반기|하반기)")
_THIS_YEAR = re.compile(r"올해|금년")
_LAST_YEAR = re.compile(r"작년|지난해")

DEFAULT_QUARTERS = 4  # 기간을 말하지 않았을 때: 최근 4분기


def parse_quarter(text: str) -> Quarter:
    """'2026Q2' / '20262' / '2026-Q2' -> (2026, 2)"""
    m = re.match(r"^(\d{4})\D*Q?([1-4])$", text.strip(), re.I)
    if not m:
        raise ValueError(f"분기 형식이 아닙니다: {text}")
    return int(m.group(1)), int(m.group(2))


def _idx(q: Quarter) -> int:
    return q[0] * 4 + q[1] - 1


def _from_idx(i: int) -> Quarter:
    return i // 4, i % 4 + 1


def label(q: Quarter) -> str:
    return f"{q[0]}Q{q[1]}"


def to_period(a: Quarter, b: Quarter) -> PeriodSpec:
    return PeriodSpec(start=f"{a[0]}-{(a[1] - 1) * 3 + 1:02d}", end=f"{b[0]}-{b[1] * 3:02d}")


def last_n(latest: Quarter, n: int) -> tuple[PeriodSpec, str]:
    start = _from_idx(_idx(latest) - n + 1)
    return to_period(start, latest), f"최근 {n}분기({label(start)}~{label(latest)})"


def quarter_aligned(p) -> bool:
    """start 월이 1·4·7·10, end 월이 3·6·9·12 인 YYYY-MM 기간."""
    try:
        sm = int(p.start.split("-")[1])
        em = int(p.end.split("-")[1])
    except (AttributeError, IndexError, ValueError):
        return False
    return sm in (1, 4, 7, 10) and em in (3, 6, 9, 12) and p.start <= p.end


def _quarters(y: str, a: int, b: int) -> PeriodSpec | None:
    if a > b:
        return None
    return PeriodSpec(start=f"{y}-{(a - 1) * 3 + 1:02d}", end=f"{y}-{b * 3:02d}")


def explicit_period(q: str) -> PeriodSpec | None:
    """질문에 명시된 기간 (2024년 1분기, 2024Q4, 2024년, 2024년 2월 ...). 없으면 None."""
    m = _Q_RANGE.search(q)
    if m:
        return _quarters(m.group(1), int(m.group(2)), int(m.group(3)))
    m = _Q_ONE.search(q) or _Q_CODE.search(q)
    if m:
        return _quarters(m.group(1), int(m.group(2)), int(m.group(2)))
    m = _DATE_RE.search(q)
    if not m:
        return None
    if m.group(1):
        y, mo = m.group(1), m.group(2)
        if mo:
            ym = f"{y}-{int(mo):02d}"
            return PeriodSpec(start=ym, end=ym)
        return PeriodSpec(start=f"{y}-01", end=f"{y}-12")
    ym = f"{m.group(3)}-{m.group(4)}"
    return PeriodSpec(start=ym, end=ym)


def relative_period(q: str, latest: Quarter) -> tuple[PeriodSpec, str] | None:
    """'최근 1년', '지난 2분기', '최근 분기', '올해', '작년' -> (기간, 설명). 없으면 None."""
    m = _YEAR_Q.search(q) or _YEAR_HALF.search(q)
    if m:  # "올해 1분기", "작년 3~4분기", "올해 상반기" -> 연도 전체가 아니라 말한 분기만
        y = latest[0] if m.group(1) in ("올해", "금년") else latest[0] - 1
        if m.re is _YEAR_HALF:
            a, b = (1, 2) if m.group(2) == "상반기" else (3, 4)
        else:
            a, b = int(m.group(2)), int(m.group(3) or m.group(2))
        if a <= b:
            span = label((y, a)) if a == b else f"{label((y, a))}~{label((y, b))}"
            return to_period((y, a), (y, b)), f"{m.group(1)} {m.group(2) + ('분기' if m.re is _YEAR_Q else '')}({span})"
    m = _REL_YEARS.search(q)
    if m and int(m.group(1)) > 0:
        return last_n(latest, int(m.group(1)) * 4)
    m = _REL_QUARTERS.search(q)
    if m and int(m.group(1)) > 0:
        return last_n(latest, int(m.group(1)))
    if _REL_ONE_Q.search(q):
        p, _ = last_n(latest, 1)
        return p, f"최근 분기({label(latest)})"
    if _THIS_YEAR.search(q):
        a = (latest[0], 1)
        return to_period(a, latest), f"올해({label(a)}~{label(latest)})"
    if _LAST_YEAR.search(q):
        y = latest[0] - 1
        return to_period((y, 1), (y, 4)), f"작년({y}년)"
    if any(w in q for w in ("최근", "요즘", "요새", "근래")):
        return last_n(latest, DEFAULT_QUARTERS)
    return None


def default_period(intent: str, latest: Quarter) -> tuple[PeriodSpec | None, str | None]:
    """기간을 말하지 않았을 때의 기본값. 추이는 전체 기간, 나머지는 최근 4분기."""
    if intent == "sales_trend":
        return None, "기간: 전체 분기"
    p, desc = last_n(latest, DEFAULT_QUARTERS)
    return p, f"기간: {desc}"
