"""대시보드(A)가 쓰는 지역 데이터를 C 데이터로 만들어 data/dashboard_data.json으로 저장한다.

기존 대시보드(dashboard/index.html의 AREAS)와 같은 키·같은 단위를 그대로 쓰고, 새 항목을 덧붙인다.
- 기존 키: id, name, dongs, rank, sales(최근 8개 분기, 억), ind(업종 TOP8 [이름, 비중%, 억]),
          day(월~일, 억), band(시간대 6구간, 억), age(10대~60대+, 억), male, female, weekday, weekend(억),
          cafe([커피 비중%, 억, 지역 안 업종 순위, 업종 수])
  - rank는 기준 분기 서울 전체 행정동(약 425개) 매출 순위, 여러 동을 합친 지역은 null (대시보드와 같은 정의,
    data/dong_rank.csv). 지도 좌표(pos)는 대시보드 쪽 값이라 여기서 만들지 않는다
- 새 키: stores(전체 점포), per_store(점포당 월평균 매출, 만 원), avg_ticket(객단가 = 매출 ÷ 결제 건수, 원),
        open_rate·close_rate(개업·폐업 점포 ÷ 전체 점포, %), franchise_rate(프랜차이즈 ÷ 전체 점포, %),
        dong_count(묶은 행정동 수), type(market=시장·도매형 / city=소비·서비스형, 대시보드와 같은 규칙),
        cautions(해석 주의 문구)
- 업종별 점포: ind_store(ind와 같은 순서 [업종, 점포 수, 점포당 월평균 매출 만 원]),
              cafe_store(커피-음료 [점포 수, 점포당 월평균 매출 만 원]). 점포 수가 0이면 매출 칸은 null
숫자는 화면 표시 규칙(docs/DATA.md 6절)대로 반올림: 억 원·% 소수 첫째 자리, 만 원·원은 정수.

사용법: python calc_engine/scripts/build_dashboard_data.py [기준분기, 예: 20262 (기본: 데이터 마지막 분기)]
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))
from calc_engine.data import DATA_SOURCE, DATA_VERSION, DEFAULT_DATA, load_sales_csv, load_store_csv  # noqa: E402

T, CNT = "당월_매출_금액", "당월_매출_건수"
BANDS = ["00~06", "06~11", "11~14", "14~17", "17~21", "21~24"]
AGES = ["10", "20", "30", "40", "50", "60_이상"]
# 상권 유형: 대시보드(dashboard/index.html TYPES)와 같은 규칙. 1위 업종이 이 이름을 포함하면 시장·도매형
MARKET = re.compile(r"청과|수산|반찬|육류|축산|농산|건어물|도매")


def eok(v):
    return round(v / 1e8, 1)


def label(q):
    return f"{q[2:4]}Q{q[4]}"


def build(sales: pd.DataFrame, stores: pd.DataFrame, area_map: pd.DataFrame, latest: str, dong_rank: pd.DataFrame) -> dict:
    quarters = sorted(q for q in sales["기준_년분기_코드"].unique() if q <= latest)[-8:]
    q = sales[sales["기준_년분기_코드"] == latest]
    st = stores[stores["기준_년분기_코드"] == latest]
    rk = dong_rank[dong_rank["기준_년분기_코드"] == latest].set_index("행정동_코드")["서울_매출_순위"]
    areas = []
    for area_id, a in area_map.groupby("area_id", sort=False):
        name = a["area_name"].iloc[0]
        d, s, sq = sales[sales["지역"] == name], q[q["지역"] == name], st[st["지역"] == name]
        total = float(s[T].sum())
        ind = s.groupby("서비스_업종_코드_명")[T].sum().sort_values(ascending=False)
        names = list(ind.index)
        cafe = float(ind.get("커피-음료", 0.0))
        store_n = int(sq["전체_점포_수"].sum())
        ind_n = sq.groupby("서비스_업종_코드_명")["전체_점포_수"].sum()

        def ind_store(k, v):
            n = int(ind_n.get(k, 0))
            return [k, n, round(v / (n * 3) / 1e4) if n else None]

        notes = []
        if len(a) > 1:
            notes.append(f"행정동 {len(a)}개 묶음이라 총매출이 커 보일 수 있어요. 점포당 매출로 비교하세요.")
        top, top_share = names[0], float(ind.iloc[0]) / total * 100
        market = bool(MARKET.search(top))
        if market:
            notes.append(f"시장·도매형 상권이에요. 1위 업종 {top}이 매출의 {top_share:.1f}%라, "
                         "창업 입지로 비교하려면 음식점·카페 같은 소매 업종만 걸러서 보세요.")
        areas.append({
            "id": area_id,
            "name": name,
            "dongs": list(a["dong_name"]),
            "rank": int(rk[a["dong_code"].iloc[0]]) if len(a) == 1 else None,
            "sales": [eok(d[d["기준_년분기_코드"] == x][T].sum()) for x in quarters],
            "ind": [[k, round(v / total * 100, 1), eok(v)] for k, v in ind.head(8).items()],
            "day": [eok(s[f"{x}요일_매출_금액"].sum()) for x in "월화수목금토일"],
            "band": [eok(s[f"시간대_{b}_매출_금액"].sum()) for b in BANDS],
            "age": [eok(s[f"연령대_{x}_매출_금액"].sum()) for x in AGES],
            "male": eok(s["남성_매출_금액"].sum()),
            "female": eok(s["여성_매출_금액"].sum()),
            "weekday": eok(s["주중_매출_금액"].sum()),
            "weekend": eok(s["주말_매출_금액"].sum()),
            "cafe": [round(cafe / total * 100, 1), eok(cafe),
                     names.index("커피-음료") + 1 if "커피-음료" in names else None, len(names)],
            # ---- 새 항목 ----
            "stores": store_n,
            "per_store": round(total / (store_n * 3) / 1e4) if store_n else None,
            "avg_ticket": round(total / float(s[CNT].sum())) if s[CNT].sum() else None,
            "open_rate": round(sq["개업_점포_수"].sum() / store_n * 100, 1) if store_n else None,
            "close_rate": round(sq["폐업_점포_수"].sum() / store_n * 100, 1) if store_n else None,
            "franchise_rate": round(sq["프랜차이즈_점포_수"].sum() / store_n * 100, 1) if store_n else None,
            "dong_count": len(a),
            "type": "market" if market else "city",
            "cautions": notes,
            "ind_store": [ind_store(k, v) for k, v in ind.head(8).items()],
            "cafe_store": ind_store("커피-음료", cafe)[1:],
        })
    return {
        "meta": {
            "latest_quarter": label(latest),
            "quarters": [label(x) for x in quarters],
            "units": {"sales·ind·day·band·age·male·female·weekday·weekend·cafe[1]": "억 원", "per_store·ind_store[2]·cafe_store[1]": "만 원 (점포당 월평균)",
                      "avg_ticket": "원 (매출 ÷ 결제 건수)", "*_rate·ind[1]·cafe[0]": "%"},
            "notes": [
                "추정 매출(신한카드 결제 기반 추정치)이며 실제 매출이 아닙니다.",
                "매출·건수는 분기 3개월 합계입니다. 점포당 매출은 ÷3 한 월평균입니다.",
                "점포 수는 프랜차이즈를 포함한 전체 점포 수입니다.",
                "성별·연령 합계는 법인 매출이 빠져 총매출보다 작습니다.",
            ],
            "source": DATA_SOURCE,
            "data_version": DATA_VERSION,
            "generated_by": "calc_engine/scripts/build_dashboard_data.py",
        },
        "areas": areas,
    }


if __name__ == "__main__":
    sales = load_sales_csv(DEFAULT_DATA)
    latest = sys.argv[1] if len(sys.argv) > 1 else sales["기준_년분기_코드"].max()
    area_map = pd.read_csv(ROOT.parent / "data" / "area_map.csv", dtype=str)
    dong_rank = pd.read_csv(ROOT / "data" / "dong_rank.csv", dtype={"기준_년분기_코드": str, "행정동_코드": str})
    out = build(sales, load_store_csv(), area_map, latest, dong_rank)
    (ROOT / "data" / "dashboard_data.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(out['areas'])}곳 저장, 기준 {out['meta']['latest_quarter']}, 분기 {out['meta']['quarters'][0]}~{out['meta']['quarters'][-1]}")
