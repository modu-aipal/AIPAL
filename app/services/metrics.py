"""질문 속 지표 표현 -> 지표 컬럼과 연산. 모델이 놓쳐도 코드가 근거 있는 지표를 잡는다."""
import re

from app.schemas.plan import MetricSpec

# 분기마다 쌓이는 '현재 값'이라 여러 분기를 합치면 중복 집계되므로 분기당 평균(avg)으로 보낸다
STOCK_COLUMNS = {"store_count", "general_store_count", "franchise_count"}
MAX_METRICS = 3

GROWTH_WORDS = ("증가", "증감", "감소", "성장", "상승", "하락")

# ---- 점포당(한 곳당) 표현: '분모 단어'와 '나누는 말'을 따로 보고, 붙어 있을 때만 인정한다 ----
_DEN = r"(?:점포|가게|매장|업소|상점|업체|사업체)"
_PER_STORE_RES = (
    re.compile(_DEN + r"\s*(?:당|별|마다)"),                                   # 점포당·가게별·매장마다
    re.compile(_DEN + r"\s*(?:하나|한\s*곳|한\s*개|1\s*곳|1\s*개)\s*(?:당|마다)?"),     # 점포 한 곳, 가게 하나당, 점포 1곳당
    re.compile(r"(?:한|1)\s*(?:곳|개|집)\s*(?:당|마다)"),                           # 한 곳당, 한 집당, 1개당
    re.compile(r"(?:한|1)\s*(?:개|곳)\s*" + _DEN),                              # 1개 점포 매출
    re.compile(_DEN + r"\s*(?:수|숫자)?\s*(?:대비|로\s*나눈|로\s*나눠|으로\s*나눈|으로\s*나눠|나누어)"),  # 점포 수 대비, 점포 수로 나눠
    re.compile(_DEN + r"\s*(?:의\s*)?(?:월\s*)?평균\s*(?:월\s*)?(?:매출|수입|판매)"),  # 가게 평균 매출
)
_STORE_COUNT_RE = re.compile(r"(?:점포|가게|매장|업소)\s*(?:수|숫자)|몇\s*(?:개|곳)")
_AVG_SALES_RE = re.compile(r"평균\s*(?:월\s*)?(?:매출|수입)|월평균|월\s*평균")
_QUARTER_AVG_RE = re.compile(r"분기\s*(?:당|별)?\s*평균")
_ANNUAL_RE = re.compile(r"연\s*매출|연간|1\s*년\s*(?:치|매출)|일\s*년")
AVG_TICKET_WORDS = ("객단가", "객 단가", "건당 금액", "결제 한 건당", "한 건당")


def is_per_store(q: str) -> bool:
    """'점포당·가게별·매장마다·한 곳당·점포 수 대비·가게 평균 매출' 같은 점포당 표현인가."""
    return any(r.search(q) for r in _PER_STORE_RES)


def wants_store_count(q: str) -> bool:
    return bool(_STORE_COUNT_RE.search(q))


def is_ambiguous_average(q: str) -> bool:
    """'평균 매출·월평균 매출'처럼 점포당인지 지역 합계 평균인지 알 수 없는 표현 (점포당 표현이 아닐 때)."""
    return bool(_AVG_SALES_RE.search(q)) and "매출" in q and not is_per_store(q) and not _QUARTER_AVG_RE.search(q)


def mentions_annual(q: str) -> bool:
    return bool(_ANNUAL_RE.search(q))


def mentions_avg_ticket(q: str) -> bool:
    return any(w in q for w in AVG_TICKET_WORDS)

# "전년 같은 분기 대비", "작년 대비", "전년 동기" -> 비교 기준을 직전 기간이 아니라 전년 같은 기간으로
YOY_RE = re.compile(r"(?:전년|작년|지난해)\s*(?:같은\s*(?:분기|기간)|동분기|동기|대비)|YoY|yoy")
YOY_SAME_QUARTER_RE = re.compile(r"같은\s*분기|동분기|동기")
TOTAL_WORDS = ("합계", "총합", "다 합", "합쳐", "전체 합", "모두 합")
RATIO_WORDS = ("비중", "비율", "퍼센트", "개업률", "폐업률")


def is_sales_column(name: str) -> bool:
    return name.endswith("_sales")


def infer_metrics(q: str, cols: set[str]) -> list[MetricSpec]:
    out: list[MetricSpec] = []

    def add(col: str, op: str) -> None:
        if col in cols and not any(m.column == col and m.op == op for m in out):
            out.append(MetricSpec(column=col, op=op))

    sales = None
    if "주말" in q:
        sales = "weekend_sales"
    elif "주중" in q or "평일" in q:
        sales = "weekday_sales"
    elif "남성" in q:
        sales = "male_sales"
    elif "여성" in q:
        sales = "female_sales"
    elif "매출" in q or is_per_store(q):
        sales = "est_sales"
    per_store = is_per_store(q)
    if per_store:
        add(sales or "est_sales", "per_store")
        if wants_store_count(q):  # "점포당 매출과 점포 수"
            add("store_count", "avg")
    elif is_ambiguous_average(q):  # 평균 매출: 점포당 월평균과 합계를 둘 다 보여 준다
        add(sales or "est_sales", "per_store")
        add(sales or "est_sales", "sum")
    elif sales:
        add(sales, "sum")

    specific_store = False
    if "프랜차이즈" in q:
        add("franchise_count", "avg")
        specific_store = True
    if "일반 점포" in q or "일반점포" in q:
        add("general_store_count", "avg")
        specific_store = True
    if "개업" in q.replace("중개업", ""):  # '부동산중개업' 같은 업종 이름 속 '개업'은 개업 점포 수가 아니다
        add("open_count", "sum")
        specific_store = True
    if "폐업" in q:
        add("close_count", "sum")
        specific_store = True
    if not per_store and not specific_store and ("점포" in q or "가게 수" in q):
        add("store_count", "avg")
    if "건수" in q or "결제 횟수" in q:
        add("est_count", "sum")
    return out[:MAX_METRICS]


def normalize_op(m: MetricSpec) -> MetricSpec:
    """점포 수처럼 쌓이는 값에 sum 이 오면 분기당 평균(avg)으로 바꾼다."""
    if m.column in STOCK_COLUMNS and m.op == "sum":
        return MetricSpec(column=m.column, op="avg")
    return m


def apply_growth(metrics: list[MetricSpec], q: str) -> list[MetricSpec]:
    """'증가·성장' 표현이 있으면 첫 지표를 증감률로 (점포당 매출은 제외)."""
    if not metrics or not any(w in q for w in GROWTH_WORDS):
        return metrics
    if any(m.op == "growth_rate" for m in metrics) or metrics[0].op == "per_store":
        return metrics
    return [MetricSpec(column=metrics[0].column, op="growth_rate"), *metrics[1:]]


SALES_OPS = ("sum", "growth_rate", "per_store")  # 매출 규모 · 증가율 · 점포당 월평균
_PRIMARY_OP = {"overall": "sum", "size": "sum", "growth": "growth_rate", "efficiency": "per_store"}


def build_metrics(intent: str, concept: str | None, explicit: list[MetricSpec],
                  model_metrics: list[MetricSpec], cols: set[str]) -> tuple[list[MetricSpec], str | None]:
    """개념과 질문 속 지표로 계산할 지표 목록과 정렬 기준(primary)을 정한다. primary 가 첫 번째.

    - 점포·개업·건수처럼 매출이 아닌 지표를 직접 말했으면 그대로 쓴다.
    - 매출 계열은 순위·업종 비교이거나 '잘나가는(overall)' 개념이면 규모·증가율·점포당 세 가지를 함께 계산해
      사용자가 '실제로 잘 나가는지' 스스로 판단할 수 있게 한다.
    """
    explicit = [normalize_op(m) for m in explicit]
    if not explicit and any(not is_sales_column(m.column) for m in model_metrics):
        explicit = list(model_metrics)  # 질문에서는 못 잡았지만 모델이 점포·건수 같은 비매출 지표를 골랐다

    def key(m: MetricSpec) -> str:
        return f"{m.column}.{m.op}"

    if explicit and any(not is_sales_column(m.column) for m in explicit):
        return explicit, key(explicit[0])
    base = next((m.column for m in [*explicit, *model_metrics] if is_sales_column(m.column)), "est_sales")
    if base not in cols:
        chosen = explicit or model_metrics
        return chosen, (key(chosen[0]) if chosen else None)
    if concept in (None, "none"):  # 개념이 없으면 말한 지표·모델 지표의 연산에서 추정
        ops = {m.op for m in explicit} | {m.op for m in model_metrics if m.column == base}
        concept = "efficiency" if "per_store" in ops else "growth" if "growth_rate" in ops else "size"
    flow = {"closures": "close_count", "openings": "open_count"}.get(concept or "")
    if flow and flow in cols:  # 폐업·개업은 그 분기에 일어난 수라 합계로 본다
        m = MetricSpec(column=flow, op="sum")
        return [m], key(m)
    if concept == "count":  # '몇 개' 표현인데 지표를 못 잡았다 -> 점포 수
        if "store_count" in cols:
            m = MetricSpec(column="store_count", op="avg")
            return [m], key(m)
        concept = "size"
    can_store = "store_count" in cols
    primary = _PRIMARY_OP.get(concept, "sum")
    if primary == "per_store" and not can_store:
        primary = "sum"
    want_trio = concept == "overall" or intent in ("ranking", "industry_comparison")
    ops = [primary, *[o for o in SALES_OPS if o != primary]] if want_trio else [primary]
    if not can_store:
        ops = [o for o in ops if o != "per_store"]
    metrics = [MetricSpec(column=base, op=o) for o in ops]
    return metrics, key(metrics[0])
