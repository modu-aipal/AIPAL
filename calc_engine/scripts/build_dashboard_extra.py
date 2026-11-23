"""대시보드 지도의 나머지 80곳(dashboard/index.html의 EXTRA)을 20곳과 같은 형식으로 만들어 data/dashboard_data_extra.json으로 저장한다.

- 80곳 목록: data/extra_area_map.csv (EXTRA의 id·이름·구·행정동 코드. id = 'd' + 행정동 코드)
- 숫자는 20곳과 같은 생성 함수(build_dashboard_data.build)로 만든다. 키·단위·반올림이 같다. 80곳은 'gu'(구) 키가 더 있다
- 80곳은 가공 데이터를 레포에 두지 않고 **원본(calc_engine/raw/, git 제외)에서 바로** 만든다 (80개 동 전체 기간이면 수십 MB라서).
  그래서 원본이 없으면 다시 만들 수 없다. 원본 받는 법은 docs/DATA.md

사용법: python calc_engine/scripts/build_dashboard_extra.py [기준분기, 예: 20262 (기본: 원본 마지막 분기)]
"""
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
sys.path.insert(0, str(ROOT.parent))
from calc_engine.data import TEXT_COLUMNS  # noqa: E402

spec = importlib.util.spec_from_file_location("bdd", ROOT / "scripts" / "build_dashboard_data.py")
bdd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bdd)

# 앞 파일이 우선 (공식 파일 → Sheet). 최근 8개 분기와 25Q4 재현에 필요한 2024년부터 읽는다
SALES_FILES = ["sales_dong_2024.csv", "sales_dong_2025.csv", "sales_dong_sheet_2025Q1_2026Q2.csv"]
STORE_FILES = ["store_dong_2024.csv", "store_dong_2025.csv", "store_dong_sheet.csv"]
KEY = ["기준_년분기_코드", "행정동_코드", "서비스_업종_코드"]
STORE_RENAME = {"점포_수": "일반_점포_수", "유사_업종_점포_수": "전체_점포_수"}


def read_raw(files, rename=None):
    frames = []
    for order, name in enumerate(files):
        df = pd.read_csv(RAW / name, encoding="cp949", dtype={"기준_년분기_코드": str, "행정동_코드": str})
        if rename and set(rename) <= set(df.columns):
            df = df.rename(columns=rename)
        df["_order"] = order
        frames.append(df)
    raw = pd.concat(frames, ignore_index=True)
    return raw.sort_values("_order").drop_duplicates(KEY, keep="first").drop(columns="_order")


def seoul_rank(sales_all):
    """분기별 서울 전체 행정동 매출 순위 (20곳 dong_rank.csv와 같은 정의)"""
    rows = []
    for q, g in sales_all.groupby("기준_년분기_코드"):
        tot = g.groupby("행정동_코드")["당월_매출_금액"].sum()
        rk = tot.rank(ascending=False, method="min").astype(int)
        rows += [(q, c, int(r), len(tot)) for c, r in rk.items()]
    return pd.DataFrame(rows, columns=["기준_년분기_코드", "행정동_코드", "서울_매출_순위", "서울_행정동_수"])


def prepare(df, area_map):
    df = df[df["행정동_코드"].isin(area_map["dong_code"])].copy()
    for col in df.columns:
        if col not in TEXT_COLUMNS:
            df[col] = pd.to_numeric(df[col]).astype("int64")
    df["지역"] = df["행정동_코드"].map(dict(zip(area_map["dong_code"], area_map["area_name"])))
    df["행정동_코드_명"] = df["행정동_코드"].map(dict(zip(area_map["dong_code"], area_map["dong_name"])))
    return df


def build_extra(latest=None):
    area_map = pd.read_csv(ROOT / "data" / "extra_area_map.csv", dtype=str)
    sales_all = read_raw(SALES_FILES)
    stores_all = read_raw(STORE_FILES, STORE_RENAME)
    latest = latest or sales_all["기준_년분기_코드"].max()
    out = bdd.build(prepare(sales_all, area_map), prepare(stores_all, area_map), area_map, latest, seoul_rank(sales_all))
    gu = dict(zip(area_map["area_id"], area_map["gu"]))
    out["areas"] = [{**{k: a[k] for k in ("id", "name", "dongs", "rank")}, "gu": gu[a["id"]],
                     **{k: v for k, v in a.items() if k not in ("id", "name", "dongs", "rank")}} for a in out["areas"]]
    out["meta"]["scope"] = "대시보드 지도의 나머지 80곳 (dashboard/index.html EXTRA)"
    out["meta"]["generated_by"] = "calc_engine/scripts/build_dashboard_extra.py"
    return out


if __name__ == "__main__":
    out = build_extra(sys.argv[1] if len(sys.argv) > 1 else None)
    (ROOT / "data" / "dashboard_data_extra.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(out['areas'])}곳 저장, 기준 {out['meta']['latest_quarter']}, 분기 {out['meta']['quarters'][0]}~{out['meta']['quarters'][-1]}")
