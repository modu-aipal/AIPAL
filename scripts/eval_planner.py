"""질문 해석 평가 도구.

사용 (저장소 최상단에서):
  python scripts/eval_planner.py --rules-only          # 모델 없이 서버 규칙만
  python scripts/eval_planner.py --model llama3.1:8b   # 실제 Ollama 모델
  python scripts/eval_planner.py --model qwen2.5:7b -v # 틀린 케이스 자세히

scripts/eval_questions.json 의 질문을 planner 에 넣고, 기대값(expect)과 비교해 정확도를 낸다.
계산 엔진은 부르지 않는다(계획 단계만 평가). 최신 분기는 2026Q2 로 고정한다.
"""
import argparse
import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(exp: dict, resp) -> list[str]:
    fails: list[str] = []
    want = exp.get("status", "ok")
    if resp.status != want:
        return [f"status {resp.status} (기대 {want})"]
    if want == "needs_clarification":
        rc = exp.get("reason_contains")
        text = (resp.reason or "") + " " + (resp.clarification_question or "")
        if rc and rc not in text:
            fails.append(f"재질문 이유에 '{rc}' 없음")
        if not resp.suggested_questions:
            fails.append("제안 질문 없음")
        return fails
    p = resp.plan
    if "intent" in exp and p.intent != exp["intent"]:
        fails.append(f"intent {p.intent} (기대 {exp['intent']})")
    if "regions" in exp and set(p.regions) != set(exp["regions"]):
        fails.append(f"regions {p.regions} (기대 {exp['regions']})")
    if "industries" in exp and set(p.industries) != set(exp["industries"]):
        fails.append(f"industries {p.industries} (기대 {exp['industries']})")
    keys = [f"{m.column}.{m.op}" for m in p.metrics]
    primary = getattr(p, "sort_by", None) or (keys[0] if keys else None)
    if "primary" in exp and primary != exp["primary"]:
        fails.append(f"primary {primary} (기대 {exp['primary']})")
    for k in exp.get("metrics_include", []):
        if k not in keys:
            fails.append(f"지표 {k} 없음 (있는 것 {keys})")
    if "top_n" in exp and getattr(p, "top_n", None) != exp["top_n"]:
        fails.append(f"top_n {getattr(p, 'top_n', None)} (기대 {exp['top_n']})")
    if "order" in exp and p.rank_order != exp["order"]:
        fails.append(f"order {p.rank_order} (기대 {exp['order']})")
    if "period" in exp:
        got = p.period.model_dump() if p.period else None
        e = exp["period"]
        if e == "last4":
            e = {"start": "2025-07", "end": "2026-06"}
        elif e == "last1":
            e = {"start": "2026-04", "end": "2026-06"}
        if got != e:
            fails.append(f"period {got} (기대 {e})")
    return fails


async def run(args) -> int:
    from app.services import planner
    from app.services.dataset import default_dataset

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    ds = default_dataset()
    rows, t0 = [], time.time()
    for c in cases:
        started = time.time()
        err = None
        try:
            if args.rules_only:
                resp = planner.evaluate(c["q"], planner._NULL_DRAFT, ds, (2026, 2))
            else:
                _, resp = await planner.make_plan(c["q"], ds)
            fails = check(c["expect"], resp)
        except Exception as e:  # 모델 오류/검증 오류도 틀린 것으로 센다
            fails, err = [f"예외 {type(e).__name__}: {str(e)[:80]}"], True
        rows.append((c, fails, time.time() - started))
        mark = "OK  " if not fails else "FAIL"
        print(f"{mark} [{c['id']:>2}] {c['q']}  ({rows[-1][2]:.1f}s)")
        if fails and (args.verbose or True):
            for f in fails:
                print(f"        - {f}")
    ok = sum(1 for _, f, _ in rows if not f)
    print("\n" + "=" * 60)
    by_tag = defaultdict(lambda: [0, 0])
    for c, f, _ in rows:
        key = c["tag"].split("-")[0] if not args.by_tag_full else c["tag"]
        by_tag[key][1] += 1
        by_tag[key][0] += 0 if f else 1
    for k, (a, b) in sorted(by_tag.items()):
        print(f"  {k:<10} {a}/{b}")
    idiom = [r for r in rows if "idiom" in r[0]["tag"]]
    print(f"  관용 표현(idiom) {sum(1 for _, f, _ in idiom if not f)}/{len(idiom)}")
    label = "규칙만" if args.rules_only else os.environ.get("OLLAMA_MODEL", "?")
    print(f"\n[{label}] 정확도 {ok}/{len(rows)} = {ok / len(rows):.0%}  (총 {time.time() - t0:.0f}s)")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="OLLAMA_MODEL 덮어쓰기")
    ap.add_argument("--rules-only", action="store_true", help="모델 없이 서버 규칙만 평가")
    ap.add_argument("--cases", default=str(ROOT / "scripts" / "eval_questions.json"))
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--by-tag-full", action="store_true")
    args = ap.parse_args()
    os.environ.setdefault("CALC_MODE", "mock")
    os.environ["LATEST_QUARTER"] = "2026Q2"
    os.environ["API_KEY"] = ""
    if args.model:
        os.environ["OLLAMA_MODEL"] = args.model
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
