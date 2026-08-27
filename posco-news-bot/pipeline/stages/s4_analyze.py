"""s4_analyze (L0 계층) — 규칙 태깅 + 추출 요약. LLM·네트워크 없음.

입력 : raw/<run_id>/normalized.jsonl   (s2 산출)
출력 : raw/<run_id>/analyzed.jsonl      (s6 publish 입력)

INV-1: 크롤링·요약은 전 트랙 공통 단일 경로. 트랙별 분기 없음.
       (policy_stage/dispute_stage 는 같은 함수가 규칙으로 채우고, 없으면 None)
INV-6: L0 산출물만으로 아카이브가 완성된다. L1(논조·생성요약)·L2(시사점·SWOT)는
       이후 enrich 로 얹히며, 여기서는 만들지 않는다.
INV-3/5: L2 비공개 필드(futurem_implication·swot_axis·sector_impact·frame 등)와
       본문 전문(body)은 이 산출물에 넣지 않는다.

요약은 L0 추출 요약(리드 문장)이다. 생성형 재작성은 L1(Ollama)의 몫이며,
analysis_level·summary_method 로 추출본임을 명시해 하류가 구분할 수 있게 한다.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Callable

from . import common
from .relevance import posco_relevance

# ── 요약 (추출) ───────────────────────────────────────────────────────────

_SENT_SPLIT = re.compile(r"(?<=[.!?…。])\s+|\n+")


def split_sentences(text: str) -> list[str]:
    text = common.collapse_ws(text)
    if not text:
        return []
    parts = _SENT_SPLIT.split(text)
    return [s.strip() for s in parts if s and s.strip()]


def extract_summary(body: str | None, description: str | None, title: str,
                    max_summary: int = 2, max_bullets: int = 5) -> dict[str, Any]:
    """리드 문장 기반 추출 요약. body 우선, 없으면 description, 그도 없으면 title."""
    if body and body.strip():
        source, text = "body", body
    elif description and description.strip():
        source, text = "description", description
    else:
        source, text = "title", title or ""

    sents = split_sentences(text)
    if not sents:
        sents = [common.collapse_ws(title)] if title else []

    summary = " ".join(sents[:max_summary]).strip()
    bullets = sents[:max_bullets]
    return {
        "summary": summary,
        "bullets": bullets,
        "summary_method": "extractive",   # L0: 추출 요약 (L1에서 생성형으로 대체)
        "summary_source": source,
    }


# ── 규칙 태깅 ─────────────────────────────────────────────────────────────

def _match_aliases(text: str, alias_map: dict[str, list[str]]) -> list[str]:
    """label→aliases 사전에서 text 에 등장하는 label 을 순서 보존해 반환."""
    low = text.lower()
    hits: list[str] = []
    for label, aliases in alias_map.items():
        for a in aliases:
            if a and a.lower() in low:
                hits.append(label)
                break
    return hits


def tag_companies(text: str, keywords: dict[str, Any]) -> list[str]:
    """그룹사(posco_entities) + 타사(company_aliases)."""
    posco = _match_aliases(text, keywords.get("posco_entities") or {})
    peers = _match_aliases(text, keywords.get("company_aliases") or {})
    seen: set[str] = set()
    return [c for c in posco + peers if not (c in seen or seen.add(c))]


def tag_countries(text: str, keywords: dict[str, Any]) -> list[str]:
    return _match_aliases(text, keywords.get("countries") or {})


def tag_topics(text: str, track: str, category: str, keywords: dict[str, Any]) -> list[str]:
    """해당 카테고리의 must/expand 중 본문에 등장한 키워드(기업·국가 제외)."""
    low = text.lower()
    cat_cfg = ((keywords.get("tracks") or {}).get(track) or {}).get(category) or {}
    company_terms = {a.lower() for al in (keywords.get("company_aliases") or {}).values() for a in al}
    country_terms = {a.lower() for al in (keywords.get("countries") or {}).values() for a in al}
    topics: list[str] = []
    seen: set[str] = set()
    for kw in (cat_cfg.get("must") or []) + (cat_cfg.get("expand") or []):
        k = kw.lower()
        if k in company_terms or k in country_terms:
            continue
        if k in low and kw not in seen:
            seen.add(kw)
            topics.append(kw)
    return topics


def affects_futurem(text: str, keywords: dict[str, Any]) -> bool:
    low = text.lower()
    return any((p or "").lower() in low for p in keywords.get("futurem_products") or [])


# source_type 판정 (news | press_release | gazette | report)
GAZETTE_OUTLETS = {"Federal Register", "관보", "전자관보", "EUR-Lex", "USTR", "BIS"}
PRESS_OUTLETS = {"정책브리핑", "korea.kr", "산업통상자원부", "기획재정부", "환경부"}
REPORT_CATS = {"pol-trend"}


def resolve_source_type(rec: dict[str, Any]) -> str:
    st = rec.get("source_type")
    if st in {"gazette", "press_release", "report"}:
        return st  # 상류(s1 extra_sources)에서 이미 분류됨
    outlet = rec.get("outlet") or ""
    url = (rec.get("canonical_url") or rec.get("url") or "").lower()
    if outlet in GAZETTE_OUTLETS or "federalregister.gov" in url or "eur-lex" in url:
        return "gazette"
    if outlet in PRESS_OUTLETS or "korea.kr" in url:
        return "press_release"
    if rec.get("category") in REPORT_CATS:
        return "report"
    return "news"


# policy_stage (T3) — 예고 단계 포착이 핵심 (선제 대응)
_POLICY_RULES = [
    ("proposed", ["입법예고", "행정예고", "규제예고", "공고", "의견수렴", "proposed rule", "개정안 공고"]),
    ("enacted",  ["공포", "제정", "의결", "가결", "통과", "final rule", "확정"]),
    ("effective", ["시행", "발효"]),
    ("amended",  ["개정", "폐지", "일부개정"]),
]


def resolve_policy_stage(text: str, track: str) -> str | None:
    low = text.lower()
    for stage, kws in _POLICY_RULES:
        if any(k.lower() in low for k in kws):
            return stage
    return "discussion" if track == "policy" else None


# dispute_stage (T4) — 원문 소스가 단계 표기 명확, 뉴스 단독은 initiated 기본
_DISPUTE_RULES = [
    ("preliminary", ["예비판정", "잠정관세"]),
    ("final",       ["최종판정", "확정판정"]),
    ("in_force",    ["발효", "부과", "관세 시행"]),
    ("negotiating", ["협상", "유예", "면제 협상"]),
    ("terminated",  ["종료", "철회", "해제", "기각"]),
    ("initiated",   ["제소", "조사개시", "조사 착수", "301조 조사", "반덤핑 조사"]),
]


def resolve_dispute_stage(text: str, track: str) -> str | None:
    low = text.lower()
    for stage, kws in _DISPUTE_RULES:
        if any(k.lower() in low for k in kws):
            return stage
    return "initiated" if track == "trade" else None


def impact_l0(rec: dict[str, Any], policy_stage: str | None, dispute_stage: str | None,
              affects: bool) -> str:
    """L0 1차 중요도. 논조(tone, L1) 반영 전 추정치."""
    rel = rec.get("posco_relevance")
    prescore = rec.get("prescore") or 0.0
    if (rel == "primary" and prescore >= 6.0) \
       or (policy_stage in {"proposed", "enacted", "amended"} and affects) \
       or (dispute_stage in {"preliminary", "final", "in_force"} and affects):
        return "high"
    if rel in {"primary", "mention"} or prescore >= 4.0 or affects:
        return "mid"
    return "low"


def build_facets(track: str, category: str, companies: list[str],
                 countries: list[str], topics: list[str]) -> list[str]:
    facets = [f"track:{track}", f"cat:{category}"]
    facets += [f"company:{c}" for c in companies]
    facets += [f"country:{c}" for c in countries]
    facets += [f"topic:{t}" for t in topics]
    return facets


# ── 단일 기사 분석 (전 트랙 공통 경로) ─────────────────────────────────────

# 정규화 산출물에서 그대로 전달하는 공개 필드
CARRY_FIELDS = [
    "id", "date", "published_at", "title", "title_slug", "outlet", "outlet_tier",
    "url", "canonical_url", "sources", "lang", "track", "also_tracks",
    "track_ambiguous", "category", "posco_relevance", "prescore", "dedup_of", "dup_count",
]

# 절대 방출 금지 (INV-3/5) — 방어적 스크린
# ⚠️ 스코프 주의: 이 스트리핑은 analyze_one 이 만드는 ★공개 articles 레코드★에만
#    적용된다. L2(P6)가 futurem_implication·swot_axis 를 생성해
#    private/data/analysis.json 에 쓰는 것은 별개의 경로이며 여기서 막지 않는다.
#    L2 쓰기 경로가 절대 이 목록/함수를 재사용하지 않도록 할 것.
FORBIDDEN_OUT = {
    "body", "futurem_implication", "swot_axis", "sector_impact", "frame",
    "tone_evidence", "policy_ask_hint", "fact_check_flags",
}


def analyze_one(rec: dict[str, Any], keywords: dict[str, Any], body: str | None = None) -> dict[str, Any]:
    title = rec.get("title") or ""
    desc = rec.get("description") or ""
    track = rec.get("track") or ""
    category = rec.get("category") or ""
    # 태깅 텍스트: 본문(있으면) + 제목 + 스니펫
    text = f"{title} {desc} {body or ''}"

    out = {k: rec.get(k) for k in CARRY_FIELDS}

    # posco_relevance 는 게이트라 정규화 값을 신뢰하되, 누락 시 L0 규칙으로 보정(fail-closed)
    if out.get("posco_relevance") is None and "posco_relevance" not in rec:
        out["posco_relevance"] = posco_relevance(title, f"{desc} {body or ''}", keywords)

    out.update(extract_summary(body, desc, title))

    companies = tag_companies(text, keywords)
    countries = tag_countries(text, keywords)
    topics = tag_topics(text, track, category, keywords)
    affects = affects_futurem(text, keywords)
    policy_stage = resolve_policy_stage(text, track)
    dispute_stage = resolve_dispute_stage(text, track)

    out["source_type"] = resolve_source_type(rec)
    out["companies"] = companies
    out["countries"] = countries
    out["topics"] = topics
    out["facets"] = build_facets(track, category, companies, countries, topics)
    out["affects_futurem"] = affects
    out["policy_stage"] = policy_stage
    out["dispute_stage"] = dispute_stage
    out["impact"] = impact_l0(rec, policy_stage, dispute_stage, affects)
    out["analysis_level"] = "L0"

    # 방어: 금지 필드가 어떤 경로로든 섞이지 않도록 제거
    for f in FORBIDDEN_OUT:
        out.pop(f, None)
    return out


def analyze(records: list[dict[str, Any]], keywords: dict[str, Any],
            body_loader: Callable[[dict[str, Any]], str | None] | None = None) -> dict[str, Any]:
    articles: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for rec in records:
        try:
            body = body_loader(rec) if body_loader else None
            articles.append(analyze_one(rec, keywords, body=body))
        except Exception as exc:  # 건별 실패는 기록 후 계속
            errors.append({"stage": "analyze", "id": rec.get("id"), "reason": repr(exc)})
    meta = {
        "count": len(articles),
        "with_body": sum(1 for a in articles if a.get("summary_source") == "body"),
        "by_impact": _count_by(articles, "impact"),
        "by_relevance": _count_by(articles, "posco_relevance"),
        "analysis_level": "L0",
    }
    return {"articles": articles, "meta": meta, "errors": errors}


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    acc: dict[str, int] = {}
    for r in rows:
        k = r.get(key)
        k = "null" if k is None else str(k)
        acc[k] = acc.get(k, 0) + 1
    return acc


# ── 본문 캐시 로더 (s3_fetch 산출물; 없으면 None → description 로 degrade) ──

def cache_body_loader(cache_dir: Path) -> Callable[[dict[str, Any]], str | None]:
    def _load(rec: dict[str, Any]) -> str | None:
        canon = rec.get("canonical_url") or rec.get("url") or ""
        if not canon:
            return None
        p = cache_dir / f"{common.sha1_hex(canon)}.json"
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data.get("body")
        except (ValueError, OSError):
            return None
    return _load


# ── CLI ──────────────────────────────────────────────────────────────────

def run(run_id: str, base_dir: Path | None = None, keywords_path: Path | None = None,
        use_cache: bool = True) -> dict[str, Any]:
    base = base_dir or (common.ROOT / "raw")
    in_path = base / run_id / "normalized.jsonl"
    out_path = base / run_id / "analyzed.jsonl"
    keywords = common.load_keywords(keywords_path)

    records = list(common.read_jsonl(in_path))
    ih = common.input_hash(records)
    meta_path = base / run_id / "analyzed.meta"
    if out_path.exists() and meta_path.exists() and meta_path.read_text().strip() == ih:
        print(f"[s4] skip (idempotent) run_id={run_id}")
        return {"skipped": True}

    loader = cache_body_loader(common.ROOT / "cache") if use_cache else None
    result = analyze(records, keywords, body_loader=loader)
    n = common.write_jsonl(out_path, result["articles"])
    meta_path.write_text(ih)
    (base / run_id / "analyzed.summary.json").write_text(
        json.dumps(result["meta"], ensure_ascii=False, indent=2)
    )
    print(f"[s4] analyzed {n} articles (L0) → {out_path}")
    print(f"[s4] meta: {result['meta']}")
    if result["errors"]:
        print(f"[s4] errors: {len(result['errors'])} (기록 후 계속)")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="s4_analyze (L0) — 규칙 태깅 + 추출 요약")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--base-dir", default=None)
    ap.add_argument("--no-cache", action="store_true", help="본문 캐시 무시(스니펫만)")
    args = ap.parse_args()
    run(args.run_id, base_dir=Path(args.base_dir) if args.base_dir else None,
        use_cache=not args.no_cache)


if __name__ == "__main__":
    main()
