"""지원 지역(상권) 20곳: 이름, 식별값, 별칭, 지역별 주의 문구.

- 이름·식별값은 data/area_map.csv (대시보드 A와 C 엔진이 같이 쓰는 매핑)에서 읽는다.
- 엔진에 보내는 지역 이름은 area_map.csv 의 area_name 이다.
- 주의 문구는 C가 만든 calc_engine/data/dashboard_data.json 의 cautions 를 쓴다.
"""
import csv
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AREA_MAP = ROOT / "data" / "area_map.csv"
DASHBOARD_DATA = ROOT / "calc_engine" / "data" / "dashboard_data.json"

# area_map.csv 를 못 읽을 때만 쓰는 최소 목록
_FALLBACK = {"성수": "seongsu", "홍대": "hongdae", "건대": "kondae", "강남": "gangnam", "이태원": "itaewon"}

# 질문 속 표현 -> area_name. 일반 낱말과 겹치는 짧은 표현(제기, 가락, 가산, 신사 등)은 일부러 뺐다.
ALIASES = {
    "홍대입구": "홍대", "서교동": "홍대",
    "건대입구": "건대", "건국대": "건대", "화양동": "건대",
    "역삼": "강남", "역삼동": "강남", "역삼1동": "강남",
    "이태원동": "이태원", "이태원1동": "이태원",
    "성수동": "성수",
    "여의도": "여의동", "압구정": "압구정동", "청담": "청담동",
    "한강로": "한강로동", "종로": "종로1~4가", "종로1·2·3·4가동": "종로1~4가",
    "영등포": "영등포동", "논현": "논현1동", "논현동": "논현1동",
    "독산": "독산1동", "독산동": "독산1동", "가락동": "가락1동", "가산디지털": "가산동",
}
# 어느 쪽인지 되물어야 하는 표현
AMBIGUOUS = {"노량진": ["노량진1동", "노량진2동"], "노량진동": ["노량진1동", "노량진2동"]}
# 구 이름: 같은 구의 동 이름과 함께 쓰이면 지역으로 보지 않는다 ("강남구 청담동" -> 청담동만)
_GU = {"강남구": "강남", "영등포구": "영등포동", "종로구": "종로1~4가"}


@lru_cache
def load_areas() -> dict[str, str]:
    """area_name -> area_id (area_map.csv 순서, 중복 제거)."""
    out: dict[str, str] = {}
    try:
        with open(AREA_MAP, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                out.setdefault(row["area_name"], row["area_id"])
    except (OSError, KeyError):
        out = {}
    return out or dict(_FALLBACK)


@lru_cache
def load_cautions() -> dict[str, list[str]]:
    """area_name -> 주의 문구 목록 (dashboard_data.json 이 없으면 비어 있음)."""
    try:
        data = json.loads(DASHBOARD_DATA.read_text(encoding="utf-8"))
        return {a["name"]: list(a.get("cautions") or []) for a in data.get("areas", [])}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def area_names() -> list[str]:
    return list(load_areas())


@dataclass
class AreaMatch:
    found: list[str] = field(default_factory=list)
    ambiguous: list[list[str]] = field(default_factory=list)


def find_areas(question: str, names: list[str] | None = None) -> AreaMatch:
    """질문 속 지역을 area_name 으로 찾는다. 긴 표현부터 매칭하고 소비한다."""
    names = names or area_names()
    table = {n: n for n in names}
    table.update({a: n for a, n in ALIASES.items() if n in names})
    amb = {a: [o for o in opts if o in names] for a, opts in AMBIGUOUS.items()}

    def scan(text: str) -> AreaMatch:
        hits: list[tuple[int, str]] = []
        amb_hits: list[tuple[int, list[str]]] = []
        rest = text
        for w in sorted({*table, *amb}, key=len, reverse=True):
            i = rest.find(w)
            if i < 0:
                continue
            if w in amb:
                if len(amb[w]) > 1 and all(a not in [h[1] for h in hits] for a in amb[w]):
                    amb_hits.append((i, amb[w]))
            elif table[w] not in [h[1] for h in hits]:
                hits.append((i, table[w]))
            rest = rest.replace(w, " " * len(w))
        return AreaMatch([n for _, n in sorted(hits)], [o for _, o in sorted(amb_hits)])

    cleaned = question
    for gu in _GU:
        cleaned = cleaned.replace(gu, " " * len(gu))
    m = scan(cleaned)
    if not m.found and not m.ambiguous:  # 구 이름만 있으면 그 구의 대표 지역으로
        for gu, n in _GU.items():
            if gu in question and n in names:
                return AreaMatch([n], [])
    return m


def caution_lines(names: list[str]) -> list[str]:
    """주어진 지역들의 주의 문구를 사용자용 문장으로 정리한다 (시장·도매형은 한 줄로 묶음)."""
    cautions = load_cautions()
    wholesale, others = [], []
    for n in dict.fromkeys(names):
        for c in cautions.get(n, []):
            if c.startswith("시장·도매형"):
                wholesale.append(n)
            else:
                others.append(f"※ {n}: {c}")
    out = []
    if wholesale:
        out.append(
            f"※ 시장·도매형 상권({', '.join(wholesale)})은 도매 거래가 섞여 있어 "
            "일반 소매 상권과 단순 비교하면 오해가 있을 수 있습니다."
        )
    return out + others
