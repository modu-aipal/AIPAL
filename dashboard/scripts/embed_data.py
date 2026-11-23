"""C 엔진의 대시보드 데이터를 dashboard/index.html 안에 넣는다.

    python dashboard/scripts/embed_data.py            # 저장소 기본 경로
    python dashboard/scripts/embed_data.py --check    # 바뀔 내용만 확인 (파일은 그대로)
    python dashboard/scripts/embed_data.py --html 다른.html --data 다른.json

- 읽는 파일: calc_engine/data/dashboard_data.json (C 가 build_dashboard_data.py 로 만든 것)
- 바꾸는 줄: index.html 의 `const DATA_META=...;` 와 `const AREAS=...;` 두 줄만
- 지도 좌표(pos)는 C 데이터에 없으므로 지금 index.html 에 있는 값을 id 로 찾아 붙인다
- 리포트 20곳은 최신 분기 매출이 큰 순서로 정렬한다 (순위 목록·"매출 1위" 답변이 이 순서를 쓴다)
- 숫자는 바꾸지 않는다. C 파일 값을 그대로 넣는다
- 지도에만 있는 80곳(EXTRA)은 calc_engine/data/dashboard_data_extra.json 이 있을 때만 바꾼다
  (`const EXTRA=` 와 `const EXTRA_QUARTERS=` 두 줄, pos·gu 는 지금 값을 id 로 붙임). 파일이 없으면 그대로 둔다
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEYS_FROM_PAGE = ["pos"]  # 대시보드에만 있는 값
META_KEYS = ["latest_quarter", "quarters", "notes", "source", "data_version"]


def js(v):
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def read_const(html, name):
    m = re.search(rf"^const {name}=(.*);$", html, re.M)
    return (json.loads(m.group(1)), m) if m else (None, None)


def merge(rows, page, keys, after="rank"):
    missing = [x["id"] for x in rows if x["id"] not in page]
    if missing:
        sys.exit(f"지도 좌표가 없는 상권: {missing} — index.html 에 pos 를 먼저 넣어 주세요")
    out = []
    for x in rows:
        y = {}
        for k, v in x.items():
            y[k] = v
            if k == after:  # 대시보드 값은 rank 뒤에 (기존 순서 유지)
                for pk in keys:
                    if pk in page[x["id"]]:
                        y[pk] = page[x["id"]][pk]
        out.append(y)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default=ROOT / "dashboard" / "index.html", type=Path)
    ap.add_argument("--data", default=ROOT / "calc_engine" / "data" / "dashboard_data.json", type=Path)
    ap.add_argument("--extra", default=ROOT / "calc_engine" / "data" / "dashboard_data_extra.json", type=Path)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    html = a.html.read_text(encoding="utf-8")
    data = json.loads(a.data.read_text(encoding="utf-8"))
    meta, areas = data["meta"], data["areas"]

    old, m = read_const(html, "AREAS")
    if m is None:
        sys.exit("index.html 에서 `const AREAS=...;` 줄을 찾지 못했습니다")
    page = {x["id"]: x for x in old}

    n = len(meta["quarters"])
    bad = [x["id"] for x in areas if len(x["sales"]) != n]
    if bad:
        sys.exit(f"sales 길이가 meta.quarters({n}개)와 다른 상권: {bad}")

    merged = merge(areas, page, KEYS_FROM_PAGE)
    merged.sort(key=lambda x: -x["sales"][-1])

    meta_out = {k: meta[k] for k in META_KEYS if k in meta}
    areas_line = f"const AREAS={js(merged)};"
    meta_line = f"const DATA_META={js(meta_out)};"

    new = html[: m.start()] + areas_line + html[m.end():]
    _, mm = read_const(new, "DATA_META")
    if mm:
        new = new[: mm.start()] + meta_line + new[mm.end():]
    else:
        i = new.index(areas_line)
        new = new[:i] + meta_line + "\n" + new[i:]

    if a.extra.exists():
        ex = json.loads(a.extra.read_text(encoding="utf-8"))
        old_ex, me = read_const(new, "EXTRA")
        if me is None:
            sys.exit("index.html 에서 `const EXTRA=...;` 줄을 찾지 못했습니다")
        xq = ex["meta"]["quarters"]
        bad = [x["id"] for x in ex["areas"] if len(x["sales"]) != len(xq)]
        if bad:
            sys.exit(f"extra sales 길이가 meta.quarters 와 다른 동: {bad}")
        ex_rows = merge(ex["areas"], {x["id"]: x for x in old_ex}, ["gu", "pos"])
        new = new[: me.start()] + f"const EXTRA={js(ex_rows)};" + new[me.end():]
        mq = re.search(r"^const EXTRA_QUARTERS=.*;$", new, re.M)
        if mq is None:
            sys.exit("index.html 에서 `const EXTRA_QUARTERS=...;` 줄을 찾지 못했습니다")
        new = new[: mq.start()] + f"const EXTRA_QUARTERS={js(xq)};" + new[mq.end():]
        print(f"지도 {len(ex_rows)}곳: {xq[0]}–{xq[-1]} ({a.extra.name})")
    else:
        print(f"지도 80곳: {a.extra.name} 없음, 그대로 둠")

    dropped = sorted(set(page) - {x["id"] for x in areas})
    print(f"{a.html}: 리포트 {len(merged)}곳, 기준 {meta['latest_quarter']} ({meta['quarters'][0]}–{meta['quarters'][-1]})")
    print("순서:", " ".join(x["name"] for x in merged))
    if dropped:
        print("C 데이터에 없어 빠지는 상권:", dropped)
    if new == html:
        print("바뀐 내용 없음")
    elif a.check:
        print("바뀔 내용 있음 (--check 이라 저장하지 않음)")
    else:
        a.html.write_text(new, encoding="utf-8")
        print("저장했습니다")


if __name__ == "__main__":
    main()
