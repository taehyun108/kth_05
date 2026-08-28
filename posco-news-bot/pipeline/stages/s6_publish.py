"""s6_publish — 공개 아카이브 발행 (fail-hard).

l1.jsonl(있으면) 또는 analyzed.jsonl 을 읽어 data/articles.json 으로 발행한다.
L0 산출물만으로도 발행이 성립해야 한다(INV-6). L2 비공개 필드·본문·내부 필드는
공개 투영에서 제거한다(INV-5/8) — 서버 fs 의 data/ 에만 쓰고 public/ 엔 두지 않는다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import common

# 공개 articles.json 필드 (docs/10-data-model.md §5.1)
PUBLIC_FIELDS = [
    "id", "date", "published_at", "title", "title_slug", "outlet", "outlet_tier",
    "source_type", "url", "canonical_url", "sources", "lang", "track", "also_tracks",
    "track_ambiguous", "category", "companies", "countries", "topics", "facets",
    "policy_stage", "dispute_stage", "affects_futurem", "posco_relevance",
    "tone", "impact", "summary", "bullets", "dedup_of", "dup_count",
    "analysis_level", "summary_method",
]
# 절대 공개 금지 (INV-3/5 방어)
FORBIDDEN = {
    "body", "_body", "futurem_implication", "swot_axis", "sector_impact", "frame",
    "tone_evidence", "policy_ask_hint", "fact_check_flags",
    "kakao_summary", "l1_reject", "l1_error",  # 발송·디버그 내부 필드
}


def to_public(article: dict[str, Any]) -> dict[str, Any]:
    out = {k: article.get(k) for k in PUBLIC_FIELDS if k in article}
    for f in FORBIDDEN:
        out.pop(f, None)
    return out


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    acc: dict[str, int] = {}
    for r in rows:
        k = r.get(key)
        k = "null" if k is None else str(k)
        acc[k] = acc.get(k, 0) + 1
    return acc


def run(run_id: str, base_dir: Path | None = None, data_dir: Path | None = None) -> dict[str, Any]:
    base = base_dir or (common.ROOT / "raw")
    data = data_dir or (common.ROOT / "data")
    # L1 산출물 우선, 없으면 L0(analyzed)
    src = base / run_id / "l1.jsonl"
    if not src.exists():
        src = base / run_id / "analyzed.jsonl"
    if not src.exists():
        raise FileNotFoundError(f"발행 입력 없음: {src} (S4 미완료)")

    records = list(common.read_jsonl(src))
    articles = [to_public(r) for r in records]

    payload = {
        "schema_version": "1.0",
        "generated_at": common.now_kst().isoformat(),
        "run_id": run_id,
        "counts": {
            "total": len(articles),
            "by_track": _count_by(articles, "track"),
            "by_analysis_level": _count_by(articles, "analysis_level"),
            "by_relevance": _count_by(articles, "posco_relevance"),
        },
        "articles": articles,
    }
    data.mkdir(parents=True, exist_ok=True)
    out_path = data / "articles.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 방어 검증: 공개 산출물에 금지 필드가 없어야 한다
    leaked = {k for a in articles for k in a if k in FORBIDDEN}
    if leaked:
        raise AssertionError(f"INV-5/8 위반: articles.json 에 금지 필드 {leaked}")

    print(f"[s6] 발행 {len(articles)}건 → {out_path} (L0만으로도 발행됨)")
    return {"output_count": len(articles), "path": str(out_path), "counts": payload["counts"],
            "source": src.name}
