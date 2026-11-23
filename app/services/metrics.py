"""질문 속 지표 표현 -> 지표 컬럼과 연산. 모델이 놓쳐도 코드가 근거 있는 지표를 잡는다."""
from app.schemas.plan import MetricSpec

# 분기마다 쌓이는 '현재 값'이라 여러 분기를 합치면 중복 집계되므로 분기당 평균(avg)으로 보낸다
STOCK_COLUMNS = {"store_count", "general_store_count", "franchise_count"}
MAX_METRICS = 3

GROWTH_WORDS = ("증가", "증감", "감소", "성장", "상승", "하락")
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
    elif "매출" in q or "점포당" in q:
        sales = "est_sales"
    per_store = "점포당" in q
    if per_store:
        add(sales or "est_sales", "per_store")
    elif sales:
        add(sales, "sum")

    specific_store = False
    if "프랜차이즈" in q:
        add("franchise_count", "avg")
        specific_store = True
    if "일반 점포" in q or "일반점포" in q:
        add("general_store_count", "avg")
        specific_store = True
    if "개업" in q:
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
