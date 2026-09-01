#!/usr/bin/env python3
"""사전 변경이 수집 물량을 얼마나 바꾸는지 ★실피드로★ 측정한다.

사전을 넓히는 결정은 감으로 하면 안 된다. 넓힌 만큼 무엇이 더 들어오고,
그중 쓸 만한 게 몇 건인지 눈으로 보고 판단하려고 만든 도구다.

입력: tests/fixtures/*.titles.json  (실호출로 받아 둔 제목 목록 — 본문 없음, INV-5)
      cache/z2-verify/*.json / *.xml   (Z2 에서 새로 캡처한 것)

사용:
  python -m scripts.measure_keywords                       # 캡처된 전 피드
  python -m scripts.measure_keywords --baseline old.yaml   # 사전 두 벌 비교
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from pipeline.stages import common, rss, s1_collect

# 커밋되는 코퍼스(제목만 — INV-5) + Z2 에서 새로 캡처한 것 둘 다 본다
CORPUS_DIRS = [common.ROOT / "tests" / "fixtures", common.ROOT / "cache" / "z2-verify"]

# 2026-09 확장으로 must 에 들어간 항목 (되돌린 사전을 만들 때 뺀다)
ADDED_MUST = {
    "battery": {
        "mat-kr": ["양극재", "음극재", "전구체", "양극소재", "음극소재", "양극활물질", "음극활물질"],
        "tech": ["건식음극", "건식양극"],
    }
}


def baseline_keywords(keywords: dict[str, Any]) -> dict[str, Any]:
    """확장 전 사전 재구성 — 추가분을 must 에서 뺀다."""
    kw = copy.deepcopy(keywords)
    for track, cats in ADDED_MUST.items():
        for cat, added in cats.items():
            cfg = ((kw.get("tracks") or {}).get(track) or {}).get(cat)
            if cfg:
                cfg["must"] = [k for k in cfg.get("must", []) if k not in added]
    return kw


def load_titles() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for d in CORPUS_DIRS:
        if not d.exists():
            continue
        for p in sorted(d.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if data.get("titles"):
                out.setdefault(data.get("feed", p.stem), data["titles"])
        for p in sorted(d.glob("*.xml")):
            items = rss.parse_items(p.read_bytes(), {"id": p.stem, "name": p.stem})
            if items:
                out.setdefault(p.stem, [f"{i['title']} {i.get('description','')}" for i in items])
    return out


def measure(titles: list[str], kw: dict[str, Any]) -> tuple[int, list[tuple[str, str, str]]]:
    hits: list[tuple[str, str, str]] = []
    for t in titles:
        m = s1_collect.match_keywords(t, kw)
        if m:
            hits.append((t, m[0][0], m[0][1]))
    return len(hits), hits


def main() -> None:
    ap = argparse.ArgumentParser(description="사전 확장 전/후 수집 물량 비교")
    ap.add_argument("--show", type=int, default=12, help="추가 통과분 표시 건수")
    ap.parse_args()

    kw_new = common.load_keywords()
    kw_old = baseline_keywords(kw_new)
    corpus = load_titles()
    if not corpus:
        raise SystemExit(f"캡처 파일이 없다: {CAPTURE_DIR}")

    print("=" * 74)
    print("사전 확장 효과 측정 (실호출로 받아 둔 피드 제목 기준)")
    print("=" * 74)
    tot_before = tot_after = tot_n = 0
    for feed, titles in corpus.items():
        before, hb = measure(titles, kw_old)
        after, ha = measure(titles, kw_new)
        gained = [h for h in ha if h[0] not in {x[0] for x in hb}]
        tot_before += before
        tot_after += after
        tot_n += len(titles)
        rate_b = before / len(titles) * 100
        rate_a = after / len(titles) * 100
        print(f"\n[{feed}] 원본 {len(titles)}건")
        print(f"  확장 전: {before:3}건 통과 ({rate_b:.0f}%)")
        print(f"  확장 후: {after:3}건 통과 ({rate_a:.0f}%)   ★+{after-before}건 (+{rate_a-rate_b:.0f}%p)★")
        for t, track, cat in gained[: 12]:
            print(f"    + [{track}/{cat}] {t[:56]}")
    print("\n" + "-" * 74)
    print(f"합계: 원본 {tot_n}건 · {tot_before} → {tot_after} (+{tot_after-tot_before}건, "
          f"통과율 {tot_before/tot_n*100:.0f}% → {tot_after/tot_n*100:.0f}%)")
    print("주의: 제목만으로 측정한 ★하한값★. 실제 수집은 description 도 보므로 더 늘어난다.")
    print("=" * 74)


if __name__ == "__main__":
    main()
