"""s2_normalize — 정규화 · 중복제거 · 사전 스코어 · 상한 · 트랙/게이트 1차 판정.

입력 : raw/<run_id>/collected.jsonl   (s1_collect 산출)
출력 : raw/<run_id>/normalized.jsonl  (s3_fetch 입력)

파이프라인 (docs/01-collect.md §4.2):
  네거티브 필터 → canonical/id → dedup L1(URL)·L2(제목) → prescore
  → 카테고리별 상한 (posco_string_hit·전재 대표는 면제) → 트랙·posco_relevance 1차

스테이지 간 통신은 파일로만. L1/L2 필드는 여기서 만들지 않는다 (INV-6, 하류 optional).
posco_relevance 는 L0 결정론 규칙 (relevance.py). LLM 미사용.
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from . import common
from .relevance import posco_relevance, posco_string_hit

TRACK_ORDER = ["posco", "battery", "policy", "trade"]

# 통신사 (대표 기사 선정 1순위 — 전재 원본)
WIRE_OUTLETS = {"연합뉴스", "뉴시스", "뉴스1", "연합인포맥스"}

RECENCY_HOURS = 6
KEYWORD_WEIGHT_CAP = 4.0


# ── 네거티브 필터 ────────────────────────────────────────────────────────

def passes_negative_filter(rec: dict[str, Any], keywords: dict[str, Any]) -> bool:
    """True = 통과(유지). 광고성·시세·부고/포토 등 제거."""
    title = rec.get("title") or ""
    outlet = rec.get("outlet") or ""

    neg_outlets = keywords.get("negative_outlets") or []  # 초안: 비움 (운영하며 축적)
    if outlet and outlet in neg_outlets:
        return False

    for kw in keywords.get("negative_keywords") or []:
        if kw in title:
            return False

    text = f"{title} {rec.get('description') or ''}"
    for pat in keywords.get("negative_patterns") or []:
        # T1(posco)은 인사 기사를 유지하므로 [인사] 패턴은 keywords 에서 이미 제외돼 있음
        try:
            if re.search(pat, text):
                return False
        except re.error:
            continue
    return True


# ── 제목 유사도 (dedup L2) ───────────────────────────────────────────────

_NON_WORD = re.compile(r"[^0-9A-Za-z가-힣]+")


def title_tokens(title: str) -> set[str]:
    norm = _NON_WORD.sub(" ", (title or "").lower())
    return {t for t in norm.split() if t}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def slugify(title: str, limit: int = 60) -> str:
    slug = _NON_WORD.sub("-", (title or "").lower()).strip("-")
    return slug[:limit].strip("-")


# ── prescore ─────────────────────────────────────────────────────────────

def outlet_tier(outlet: str, keywords: dict[str, Any]) -> int:
    tiers = keywords.get("outlet_tiers") or {}
    for tier, outlets in tiers.items():
        if outlet in outlets:
            return int(tier)
    return 3  # 기타


def _keyword_weight(text: str, category_cfg: dict[str, Any]) -> float:
    must = category_cfg.get("must") or []
    expand = category_cfg.get("expand") or []
    w = 0.0
    for kw in must:
        if kw and kw.lower() in text:
            w += 2.0
    for kw in expand:
        if kw and kw.lower() in text:
            w += 1.0
    return min(w, KEYWORD_WEIGHT_CAP)


def compute_prescore(
    rec: dict[str, Any],
    keywords: dict[str, Any],
    category_cfg: dict[str, Any],
    now: datetime,
) -> float:
    text = f"{rec.get('title') or ''} {rec.get('description') or ''}".lower()

    tier = outlet_tier(rec.get("outlet") or "", keywords)
    outlet_tier_weight = {1: 3.0, 2: 2.0}.get(tier, 1.0)

    keyword_weight = _keyword_weight(text, category_cfg)

    posco_hit = 3.0 if rec.get("_posco_hit") else 0.0

    recency_weight = 0.0
    pub = common.parse_dt(rec.get("published_at"))
    if pub and (now - pub).total_seconds() <= RECENCY_HOURS * 3600:
        recency_weight = 1.0

    dup_count = rec.get("dup_count") or 0
    duplicate_penalty = 0.5 * max(0, dup_count - 1)

    return round(outlet_tier_weight + keyword_weight + posco_hit + recency_weight - duplicate_penalty, 3)


# ── 트랙 확정 ────────────────────────────────────────────────────────────

def resolve_track(candidates: list[tuple[str, str]], text: str, keywords: dict[str, Any]) -> tuple[str, list[str], bool]:
    """candidates: [(track, category), ...] → (track, also_tracks, ambiguous).

    같은 기사가 여러 카테고리 쿼리에서 잡혔을 때 대표 트랙을 정한다.
    점수 = 해당 카테고리 키워드 가중. 동점이면 TRACK_ORDER 우선.
    """
    tracks_cfg = keywords.get("tracks") or {}
    low = text.lower()
    best_track = candidates[0][0]
    best_score = -1.0
    per_track_best: dict[str, float] = {}
    for track, category in candidates:
        cat_cfg = (tracks_cfg.get(track) or {}).get(category) or {}
        score = _keyword_weight(low, cat_cfg)
        per_track_best[track] = max(per_track_best.get(track, 0.0), score)
        rank = TRACK_ORDER.index(track) if track in TRACK_ORDER else len(TRACK_ORDER)
        best_rank = TRACK_ORDER.index(best_track) if best_track in TRACK_ORDER else len(TRACK_ORDER)
        if score > best_score or (score == best_score and rank < best_rank):
            best_score, best_track = score, track

    distinct = [t for t in TRACK_ORDER if t in per_track_best]
    also = [t for t in distinct if t != best_track]
    return best_track, also, len(distinct) > 1


# ── 대표 기사 선정 (dedup 클러스터) ──────────────────────────────────────

def _rep_sort_key(rec: dict[str, Any], keywords: dict[str, Any]) -> tuple:
    outlet = rec.get("outlet") or ""
    is_wire = 0 if outlet in WIRE_OUTLETS else 1        # 통신사 우선
    tier = outlet_tier(outlet, keywords)                # 티어 상위 우선
    pub = common.parse_dt(rec.get("published_at"))
    pub_key = pub.timestamp() if pub else float("inf")  # 발행 빠른 것 우선
    return (is_wire, tier, pub_key)


# ── 메인 정규화 ──────────────────────────────────────────────────────────

def normalize(
    collected: list[dict[str, Any]],
    keywords: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """collected 레코드 → 정규화·dedup·상한 적용 결과.

    반환: {"articles": [...kept...], "meta": {...카운트...}, "errors": [...]}
    """
    now = now or common.now_kst()
    errors: list[dict[str, Any]] = []

    # 1) 네거티브 필터 + canonical + id
    staged: list[dict[str, Any]] = []
    for rec in collected:
        try:
            if not passes_negative_filter(rec, keywords):
                continue
            url = rec.get("url") or ""
            canon = common.canonical_url(url)
            if not canon:
                errors.append({"stage": "canonical", "url": url, "reason": "empty canonical"})
                continue
            date = common.to_kst_date(rec.get("published_at"), fallback=now)
            aid = common.make_article_id(canon, date)
            r = dict(rec)
            r["canonical_url"] = canon
            r["id"] = aid
            r["date"] = date
            staged.append(r)
        except Exception as exc:  # 건별 실패는 기록 후 계속
            errors.append({"stage": "normalize", "url": rec.get("url"), "reason": repr(exc)})

    # 2) dedup L1 — canonical URL 완전 일치 병합
    by_canon: dict[str, dict[str, Any]] = {}
    for r in staged:
        canon = r["canonical_url"]
        if canon not in by_canon:
            r["sources"] = list(dict.fromkeys([r.get("source")] if r.get("source") else []))
            r["_candidates"] = [(r.get("track"), r.get("category"))]
            by_canon[canon] = r
        else:
            base = by_canon[canon]
            if r.get("source"):
                base["sources"] = list(dict.fromkeys(base["sources"] + [r["source"]]))
            base["_candidates"].append((r.get("track"), r.get("category")))
            # 발행 시각이 더 이르면 대체 후보로만 참고 (대표는 아래서 선정)
    l1 = list(by_canon.values())

    # 3) dedup L2 — 제목 유사도 ≥ 0.9 클러스터
    for r in l1:
        r["_tokens"] = title_tokens(r.get("title") or "")
    clusters: list[list[dict[str, Any]]] = []
    for r in l1:
        placed = False
        for cluster in clusters:
            if jaccard(r["_tokens"], cluster[0]["_tokens"]) >= 0.9:
                cluster.append(r)
                placed = True
                break
        if not placed:
            clusters.append([r])

    kept: list[dict[str, Any]] = []
    for cluster in clusters:
        # 클러스터 후보를 대표 선정 기준으로 정렬
        cluster.sort(key=lambda x: _rep_sort_key(x, keywords))
        rep = cluster[0]
        members = cluster[1:]
        # 대표에 후보 트랙·소스 병합
        for m in members:
            rep["_candidates"].extend(m["_candidates"])
            rep["sources"] = list(dict.fromkeys(rep["sources"] + m.get("sources", [])))
        rep["dedup_of"] = None
        rep["dup_count"] = len(members)  # 흡수한 유사기사 수
        kept.append(rep)
        # 멤버는 하류로 내려보내지 않음(대표만). dedup_of 포인터 정보만 남긴다.

    # 4) 트랙 확정 · posco_relevance · posco_string_hit · prescore
    tracks_cfg = keywords.get("tracks") or {}
    for r in kept:
        title = r.get("title") or ""
        desc = r.get("description") or ""
        text = f"{title} {desc}"

        cands = [c for c in r["_candidates"] if c[0]]
        if not cands:
            cands = [(r.get("track") or "battery", r.get("category") or "")]
        track, also, ambiguous = resolve_track(cands, text, keywords)
        r["track"] = track
        r["also_tracks"] = also
        r["track_ambiguous"] = ambiguous
        # 대표 트랙에 해당하는 카테고리 하나를 고른다 (prescore 계산용)
        cat = next((c for t, c in cands if t == track), r.get("category") or "")
        r["category"] = cat
        cat_cfg = (tracks_cfg.get(track) or {}).get(cat) or {}

        r["_posco_hit"] = posco_string_hit(title, desc, keywords)
        r["posco_relevance"] = posco_relevance(title, desc, keywords)  # None 가능 (fail-closed)
        r["prescore"] = compute_prescore(r, keywords, cat_cfg, now)
        r["outlet_tier"] = outlet_tier(r.get("outlet") or "", keywords)
        r["title_slug"] = slugify(title)
        # 상한 면제: 포스코 문자열 히트 OR 전재 대표(여러 소스/유사기사 흡수)
        r["cap_exempt"] = bool(
            r["_posco_hit"] or len(r.get("sources", [])) > 1 or (r.get("dup_count") or 0) > 0
        )

    # 5) 카테고리별 일일 상한 (면제 건은 슬롯을 소비하지 않는다)
    kept_after_cap: list[dict[str, Any]] = []
    dropped_by_cap = 0
    by_category: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in kept:
        by_category.setdefault((r["track"], r["category"]), []).append(r)

    for (track, cat), rows in by_category.items():
        cat_cfg = (tracks_cfg.get(track) or {}).get(cat) or {}
        cap = cat_cfg.get("daily_cap", None)
        exempt = [r for r in rows if r["cap_exempt"]]
        capped = [r for r in rows if not r["cap_exempt"]]
        if cap is None:
            kept_after_cap.extend(exempt + capped)
            continue
        capped.sort(key=lambda x: x["prescore"], reverse=True)
        survivors = capped[: int(cap)]
        dropped_by_cap += len(capped) - len(survivors)
        kept_after_cap.extend(exempt + survivors)

    # 6) 내부 필드 정리 후 출력 스키마로
    articles = [_project(r) for r in kept_after_cap]
    articles.sort(key=lambda a: (a["track"], -a["prescore"]))

    meta = {
        "generated_at": now.isoformat(),
        "counts": {
            "collected": len(collected),
            "after_negative": len(staged),
            "after_dedup_l1": len(l1),
            "after_dedup_l2": len(kept),
            "dropped_by_cap": dropped_by_cap,
            "kept": len(articles),
            "by_track": _count_by(articles, "track"),
            "by_relevance": _count_by(articles, "posco_relevance"),
            "cap_exempt": sum(1 for a in articles if a["cap_exempt"]),
        },
    }
    return {"articles": articles, "meta": meta, "errors": errors}


PUBLIC_FIELDS = [
    "id", "date", "published_at", "title", "title_slug", "outlet", "outlet_tier",
    "source_type", "url", "canonical_url", "sources", "lang", "track", "also_tracks",
    "track_ambiguous", "category", "posco_relevance", "prescore", "cap_exempt",
    "dedup_of", "dup_count", "description",
]


def _project(r: dict[str, Any]) -> dict[str, Any]:
    out = {k: r.get(k) for k in PUBLIC_FIELDS}
    out.setdefault("dedup_of", None)
    out["dup_count"] = r.get("dup_count", 0)
    return out


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    acc: dict[str, int] = {}
    for r in rows:
        k = r.get(key)
        k = "null" if k is None else str(k)
        acc[k] = acc.get(k, 0) + 1
    return acc


# ── CLI ──────────────────────────────────────────────────────────────────

def run(run_id: str, base_dir: Path | None = None, keywords_path: Path | None = None) -> dict[str, Any]:
    base = base_dir or (common.ROOT / "raw")
    in_path = base / run_id / "collected.jsonl"
    out_path = base / run_id / "normalized.jsonl"
    keywords = common.load_keywords(keywords_path)

    collected = list(common.read_jsonl(in_path))

    # 멱등성: 출력 존재 + 동일 input_hash 면 스킵
    ih = common.input_hash(collected)
    meta_path = base / run_id / "normalized.meta"
    if out_path.exists() and meta_path.exists() and meta_path.read_text().strip() == ih:
        print(f"[s2] skip (idempotent) run_id={run_id}")
        return {"skipped": True}

    result = normalize(collected, keywords)
    n = common.write_jsonl(out_path, result["articles"])
    meta_path.write_text(ih)
    (base / run_id / "normalized.summary.json").write_text(
        __import__("json").dumps(result["meta"], ensure_ascii=False, indent=2)
    )
    print(f"[s2] normalized {n} articles → {out_path}")
    print(f"[s2] counts: {result['meta']['counts']}")
    if result["errors"]:
        print(f"[s2] errors: {len(result['errors'])} (기록 후 계속)")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="s2_normalize — 정규화·dedup·상한·게이트 1차")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--base-dir", default=None)
    args = ap.parse_args()
    run(args.run_id, base_dir=Path(args.base_dir) if args.base_dir else None)


if __name__ == "__main__":
    main()
