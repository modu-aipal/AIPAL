"""정답표 초안: 같은 질문을 pandas와 파이썬 기본 csv로 따로 계산해, 두 결과가 같을 때만 data/answer_key.md에 쓴다.

사용법: python calc_engine/scripts/answer_key.py
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "sales_5regions.csv"
STORES = ROOT / "data" / "stores_5regions.csv"
S = "전체_점포_수"
STORE_COLS = ("전체_점포_수", "일반_점포_수", "프랜차이즈_점포_수", "개업_점포_수", "폐업_점포_수")
T = "당월_매출_금액"
LATEST = "20254"
REGIONS = ["성수", "홍대", "건대", "강남", "이태원"]


# ---- 방법 1: pandas ----
def by_pandas():
    df = pd.read_csv(DATA, dtype={"기준_년분기_코드": str, "행정동_코드": str})
    st = pd.read_csv(STORES, dtype={"기준_년분기_코드": str, "행정동_코드": str})
    q = df[df["기준_년분기_코드"] == LATEST]
    seongsu_q = q[q["지역"] == "성수"]
    return {
        "Q1": int(q[T].sum()),
        "Q2": {k: int(v) for k, v in q.groupby("지역")[T].sum().items()},
        "Q3": {k: int(v) for k, v in q[q["서비스_업종_코드_명"] == "커피-음료"].groupby("지역")[T].sum().items()},
        "Q4": {k: int(v) for k, v in df[(df["지역"] == "성수") & (df["서비스_업종_코드_명"] == "커피-음료")].groupby("기준_년분기_코드")[T].sum().items()},
        "Q5": {k: (int(r["주중_매출_금액"]), int(r["주말_매출_금액"])) for k, r in q.groupby("지역")[["주중_매출_금액", "주말_매출_금액"]].sum().iterrows()},
        "Q6": (int(seongsu_q[T].sum()), {k: int(v) for k, v in seongsu_q.groupby("행정동_코드_명")[T].sum().items()}),
        "Q7": (int(q[T].sum()), int(q["남성_매출_금액"].sum() + q["여성_매출_금액"].sum())),
        "Q8": [(k, int(v)) for k, v in seongsu_q.groupby("서비스_업종_코드_명")[T].sum().sort_values(ascending=False).head(8).items()],
        "Q9": {k: (int(g["시간대_21~24_매출_금액"].sum() + g["시간대_00~06_매출_금액"].sum()), int(g[T].sum())) for k, g in q.groupby("지역")},
        "Q10": (int(df[(df["지역"] == "이태원") & (df["기준_년분기_코드"] == LATEST)][T].sum()),
                int(df[(df["지역"] == "이태원") & (df["기준_년분기_코드"] == "20244")][T].sum())),
        "Q11": tuple(int(df[(df["기준_년분기_코드"] == "20262") & (df["행정동_코드"] == "11440660")][c].sum())
                     for c in (T, "당월_매출_건수")),
        "Q12": tuple(int(st[(st["기준_년분기_코드"] == LATEST) & (st["행정동_코드"] == "11440660")][c].sum())
                     for c in STORE_COLS),
        "Q13": {k: (int(df[(df["기준_년분기_코드"] == "20262") & (df["지역"] == k)][T].sum()), int(v))
                for k, v in st[st["기준_년분기_코드"] == "20262"].groupby("지역")[S].sum().items()},
    }


# ---- 방법 2: 파이썬 기본 csv ----
def by_csv():
    with open(DATA, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    with open(STORES, encoding="utf-8-sig", newline="") as f:
        srows = list(csv.DictReader(f))
    q = [r for r in rows if r["기준_년분기_코드"] == LATEST]
    n = lambda r, c: int(r[c])

    def total(rs, key):
        acc = defaultdict(int)
        for r in rs:
            acc[key(r)] += n(r, T)
        return dict(acc)

    q5 = defaultdict(lambda: [0, 0])
    for r in q:
        q5[r["지역"]][0] += n(r, "주중_매출_금액")
        q5[r["지역"]][1] += n(r, "주말_매출_금액")
    seongsu_q = [r for r in q if r["지역"] == "성수"]
    q9 = defaultdict(lambda: [0, 0])
    for r in q:
        q9[r["지역"]][0] += n(r, "시간대_21~24_매출_금액") + n(r, "시간대_00~06_매출_금액")
        q9[r["지역"]][1] += n(r, T)
    return {
        "Q1": sum(n(r, T) for r in q),
        "Q2": total(q, lambda r: r["지역"]),
        "Q3": total([r for r in q if r["서비스_업종_코드_명"] == "커피-음료"], lambda r: r["지역"]),
        "Q4": total([r for r in rows if r["지역"] == "성수" and r["서비스_업종_코드_명"] == "커피-음료"], lambda r: r["기준_년분기_코드"]),
        "Q5": {k: tuple(v) for k, v in q5.items()},
        "Q6": (sum(n(r, T) for r in seongsu_q), total(seongsu_q, lambda r: r["행정동_코드_명"])),
        "Q7": (sum(n(r, T) for r in q), sum(n(r, "남성_매출_금액") + n(r, "여성_매출_금액") for r in q)),
        "Q8": sorted(total(seongsu_q, lambda r: r["서비스_업종_코드_명"]).items(), key=lambda kv: -kv[1])[:8],
        "Q9": {k: (v[0], v[1]) for k, v in q9.items()},
        "Q10": (sum(n(r, T) for r in rows if r["지역"] == "이태원" and r["기준_년분기_코드"] == LATEST),
                sum(n(r, T) for r in rows if r["지역"] == "이태원" and r["기준_년분기_코드"] == "20244")),
        "Q11": tuple(sum(n(r, c) for r in rows if r["기준_년분기_코드"] == "20262" and r["행정동_코드"] == "11440660")
                     for c in (T, "당월_매출_건수")),
        "Q12": tuple(sum(n(r, c) for r in srows if r["기준_년분기_코드"] == LATEST and r["행정동_코드"] == "11440660")
                     for c in STORE_COLS),
        "Q13": {k: (sum(n(r, T) for r in rows if r["기준_년분기_코드"] == "20262" and r["지역"] == k),
                    sum(n(r, S) for r in srows if r["기준_년분기_코드"] == "20262" and r["지역"] == k))
                for k in sorted({r["지역"] for r in srows})},
    }


a, b = by_pandas(), by_csv()
mismatch = [k for k in a if a[k] != b[k]]
if mismatch:
    sys.exit(f"두 계산이 다름: {mismatch}")

eok = lambda v: f"{v / 1e8:,.1f}억"
won = lambda v: f"{v:,}원"
rank = lambda d: sorted(d.items(), key=lambda kv: -kv[1])
dong_count = pd.read_csv(ROOT / "data" / "region_map.csv")["지역"].value_counts().to_dict()

L = [
    "# 정답표 초안",
    "",
    "- 데이터: `data/sales_5regions.csv` (서울시 상권분석서비스 추정매출-행정동, 2021년 1분기~2026년 2분기, 단위 원)",
    "- Q1~Q10은 2025년 4분기 기준(공식 파일 마지막 분기). Q11은 2026년 2분기(Sheet 내려받기)",
    "- 계산: pandas와 파이썬 기본 csv로 따로 계산해 **두 결과가 모두 같음**을 확인함 (`python calc_engine/scripts/answer_key.py`)",
    "- 엑셀 등 세 번째 방법으로 사람이 다시 확인하기 전까지는 '초안'",
    f"- 기준 분기: {LATEST} (2025년 4분기). 지역 = `data/region_map.csv`의 행정동 묶음",
    "",
    "## Q1. 2025년 4분기 5개 지역 전체 추정매출",
    f"- {won(a['Q1'])} ({eok(a['Q1'])})",
    "",
    "## Q2. 2025년 4분기 지역별 추정매출 순위",
    "| 순위 | 지역 | 포함 동 개수 | 매출 |",
    "|---|---|---|---|",
    *[f"| {i} | {k} | {dong_count[k]} | {won(v)} ({eok(v)}) |" for i, (k, v) in enumerate(rank(a["Q2"]), 1)],
    "",
    "주의: 성수는 동 4개, 나머지는 1개라 총액 비교는 동 개수 차이를 함께 봐야 함",
    "",
    "## Q3. 2025년 4분기 '커피-음료' 지역 순위",
    "| 순위 | 지역 | 매출 |",
    "|---|---|---|",
    *[f"| {i} | {k} | {won(v)} ({eok(v)}) |" for i, (k, v) in enumerate(rank(a["Q3"]), 1)],
    "",
    "## Q4. 성수 '커피-음료' 분기별 추이",
    "| 분기 | 매출 |",
    "|---|---|",
    *[f"| {k} | {won(v)} ({eok(v)}) |" for k, v in sorted(a["Q4"].items())],
    "",
    "## Q5. 2025년 4분기 지역별 주중 vs 주말",
    "| 지역 | 주중 | 주말 | 주말 비중 |",
    "|---|---|---|---|",
    *[f"| {k} | {eok(a['Q5'][k][0])} | {eok(a['Q5'][k][1])} | {a['Q5'][k][1] / sum(a['Q5'][k]) * 100:.1f}% |" for k in REGIONS],
    "",
    "## Q6. 성수 합계 = 4개 동 합계의 합 (매핑 합치기 검증, 2025년 4분기)",
    f"- 성수 합계: {won(a['Q6'][0])}",
    *[f"- {k}: {won(v)}" for k, v in sorted(a["Q6"][1].items())],
    f"- 4개 동 합: {won(sum(a['Q6'][1].values()))} → {'같음' if sum(a['Q6'][1].values()) == a['Q6'][0] else '다름'}",
    "",
    "## Q7. 남성+여성 매출이 총매출과 같은가? (2025년 4분기, 5개 지역)",
    f"- 총매출: {won(a['Q7'][0])}",
    f"- 남성+여성: {won(a['Q7'][1])}",
    f"- 차이: {won(a['Q7'][0] - a['Q7'][1])} → 같지 않음. 기대 답변: 법인 매출은 성별·연령 정보가 없어 성별 합계가 총매출보다 작을 수 있음 (데이터 페이지 FAQ)",
    "",
    "## Q8. 2025년 4분기 성수 업종 TOP 8",
    "| 순위 | 업종 | 매출 |",
    "|---|---|---|",
    *[f"| {i} | {k} | {won(v)} ({eok(v)}) |" for i, (k, v) in enumerate(a["Q8"], 1)],
    "",
    "## Q9. 2025년 4분기 야간(21~24시 + 00~06시) 매출 비중 순위",
    "| 순위 | 지역 | 야간 매출 | 총매출 | 비중 |",
    "|---|---|---|---|---|",
    *[f"| {i} | {k} | {won(v[0])} | {won(v[1])} | {v[0] / v[1] * 100:.1f}% |" for i, (k, v) in enumerate(sorted(a["Q9"].items(), key=lambda kv: -kv[1][0] / kv[1][1]), 1)],
    "",
    "## Q10. 이태원 2025년 4분기 전년 같은 분기(2024년 4분기) 대비",
    f"- 2025년 4분기: {won(a['Q10'][0])}",
    f"- 2024년 4분기: {won(a['Q10'][1])}",
    f"- 증감률: {(a['Q10'][0] / a['Q10'][1] - 1) * 100:+.2f}%",
    "",
    "## Q11. 서교동 2026년 2분기 (상권분석서비스 사이트와 대조)",
    f"- 매출: {won(a['Q11'][0])} ({eok(a['Q11'][0])}) — 사이트 지도 표시 3,642.8억 원",
    f"- 매출 ÷3 ÷점포수 8,783 = {a['Q11'][0] / 3 / 8783:,.0f}원 — 사이트 '점포당 월평균 매출' 1,383만 원",
    f"- 건수 ÷3 ÷8,783 = {a['Q11'][1] / 3 / 8783:,.1f}건 — 사이트 '월평균 매출건수' 582건",
    "- 점포수 8,783개는 사이트 표시값. 매출·건수가 분기 3개월 합계라는 근거",
    "",
    "## Q12. 서교동 2025년 4분기 점포 (점포 데이터 OA-22172, 사이트와 대조)",
    f"- 전체 점포 {a['Q12'][0]:,} / 일반 {a['Q12'][1]:,} / 프랜차이즈 {a['Q12'][2]:,} / 개업 {a['Q12'][3]:,} / 폐업 {a['Q12'][4]:,}",
    "- 사이트: 점포수 8,820 / 일반점포 8,101 / 프랜차이즈 719 / 개업 223 / 폐업 239",
    "- 원본 '점포_수'는 일반 점포, '유사_업종_점포_수'가 전체 점포 (가공 파일은 일반_점포_수·전체_점포_수로 이름을 바꿈)",
    "",
    "## Q13. 2026년 2분기 지역별 점포당 월평균 매출 (매출 ÷ (전체 점포 × 3))",
    "| 순위 | 지역 | 매출 | 전체 점포 | 점포당 월평균 |",
    "|---|---|---|---|---|",
    *[f"| {i} | {k} | {eok(v[0])} | {v[1]:,} | {v[0] / (v[1] * 3) / 1e4:,.0f}만 원 |"
      for i, (k, v) in enumerate(sorted(a["Q13"].items(), key=lambda kv: -kv[1][0] / (kv[1][1] * 3)), 1)],
    "",
    "점포당으로 보면 총매출 순위와 달라질 수 있음 (성수는 동 4개라 총매출이 커 보임). 점포 수에는 매출이 없는 업종 점포도 포함 (사이트와 같은 방식)",
    "",
]
(ROOT / "data" / "answer_key.md").write_text("\n".join(L), encoding="utf-8")
print("두 계산 일치. data/answer_key.md 저장")
