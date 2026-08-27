#!/usr/bin/env python3
"""Z2 실데이터 스모크 — s1_collect 만 실행해 실제 응답을 검증한다.

목적: 합성 fixture 로는 못 잡는 실제 네이버/구글 응답의
      필드 매핑·인코딩·페이징을 확인한다. (P2 착수 전 게이트)

동작:
  1. .env 에서 네이버 키를 읽어 s1_collect 실행 (키 없으면 구글 RSS 만, fail-soft)
  2. 트랙 하나(기본 posco/futurem)로 최근 N시간(기본 24h) 수집
  3. 원본 HTTP 응답은 cache/smoke/ 에 저장 (.gitignore — 커밋 안 됨)
  4. tests/fixtures/ 에는 ★메타데이터 + 200자 이내 발췌만★ 저장 (INV-5)
  5. 수집 건수·필드 누락·인코딩 이상 리포트를 stdout 에 출력

사용:
  cd posco-news-bot
  cp .env.example .env && vi .env        # NAVER_CLIENT_ID/SECRET 채우기
  python -m scripts.smoke_collect                       # posco/futurem, 24h
  python -m scripts.smoke_collect --track battery --category cell-kr --hours 48
  python -m scripts.smoke_collect --no-naver            # 구글 RSS 만
"""
from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
from datetime import timedelta
from pathlib import Path
from typing import Any

from pipeline.stages import common, s1_collect

EXCERPT_LIMIT = 200  # INV-5: 발췌 상한 (본문 전문 금지)
MAX_FIXTURE_SAMPLES = 30

# 검증할 필드 (필수 / 참고)
REQUIRED_FIELDS = ["title", "url", "published_at"]
REPORT_FIELDS = ["title", "url", "published_at", "outlet", "description"]

# 인코딩 이상 탐지
_REPLACEMENT = "�"                                   # U+FFFD (깨진 문자)
_LEFTOVER_ENTITY = re.compile(r"&(?:amp|lt|gt|quot|#\d+|#x[0-9a-fA-F]+);")  # 미복원 엔티티
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")    # 제어문자


def excerpt(text: str | None) -> str:
    """INV-5: 200자 이내 발췌. 앞뒤 공백 정리."""
    t = common.collapse_ws(text or "")
    return t[:EXCERPT_LIMIT]


def sanitize(rec: dict[str, Any]) -> dict[str, Any]:
    """fixture 저장용 — 본문 전문 없이 메타데이터 + 발췌만."""
    return {
        "title": rec.get("title"),
        "url": rec.get("url"),
        "outlet": rec.get("outlet"),
        "published_at": rec.get("published_at"),
        "source": rec.get("source"),
        "lang": rec.get("lang"),
        "track": rec.get("track"),
        "category": rec.get("category"),
        "excerpt": excerpt(rec.get("description")),
    }


def within_hours(rec: dict[str, Any], hours: int, now) -> bool:
    pub = common.parse_dt(rec.get("published_at"))
    if pub is None:
        return True  # 시각 미상은 일단 포함 (필드 누락 리포트에서 별도 카운트)
    return (now - pub).total_seconds() <= hours * 3600


def find_encoding_issues(rec: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for field in ("title", "description"):
        val = rec.get(field) or ""
        if _REPLACEMENT in val:
            issues.append(f"{field}: U+FFFD 치환문자")
        if _LEFTOVER_ENTITY.search(val):
            issues.append(f"{field}: 미복원 HTML 엔티티")
        if _CONTROL.search(val):
            issues.append(f"{field}: 제어문자")
        # NFC 정규화 시 길이가 변하면 자모 분리(조합형) 의심
        if val and unicodedata.normalize("NFC", val) != val:
            issues.append(f"{field}: 유니코드 정규화(NFC) 불일치")
    return issues


def report(records: list[dict[str, Any]], errors: list[dict[str, Any]], hours: int, now) -> dict[str, Any]:
    total = len(records)
    by_source: dict[str, int] = {}
    for r in records:
        by_source[r.get("source", "?")] = by_source.get(r.get("source", "?"), 0) + 1

    recent = [r for r in records if within_hours(r, hours, now)]

    # 필드 누락 통계
    field_missing = {f: 0 for f in REPORT_FIELDS}
    for r in records:
        for f in REPORT_FIELDS:
            v = r.get(f)
            if v is None or (isinstance(v, str) and not v.strip()):
                field_missing[f] += 1

    required_broken = [
        {"url": r.get("url"), "missing": [f for f in REQUIRED_FIELDS
                                          if not (r.get(f) and str(r.get(f)).strip())]}
        for r in records
        if any(not (r.get(f) and str(r.get(f)).strip()) for f in REQUIRED_FIELDS)
    ]

    enc_hits = []
    for r in records:
        iss = find_encoding_issues(r)
        if iss:
            enc_hits.append({"title": excerpt(r.get("title"))[:60], "issues": iss})

    # 중복(canonical) 사전 점검 — 실데이터 dedup 예상치
    canon = {}
    for r in records:
        c = common.canonical_url(r.get("url") or "")
        canon[c] = canon.get(c, 0) + 1
    dup_canon = {c: n for c, n in canon.items() if n > 1}

    return {
        "collected_total": total,
        "by_source": by_source,
        "within_%dh" % hours: len(recent),
        "field_missing": field_missing,
        "required_broken_count": len(required_broken),
        "required_broken_samples": required_broken[:5],
        "encoding_issue_count": len(enc_hits),
        "encoding_issue_samples": enc_hits[:5],
        "duplicate_canonical_groups": len(dup_canon),
        "source_errors": errors,
    }


def print_report(rep: dict[str, Any], hours: int) -> None:
    line = "=" * 64
    print(line)
    print("실데이터 스모크 리포트 (s1_collect)")
    print(line)
    print(f"수집 총건수      : {rep['collected_total']}")
    print(f"소스별           : {rep['by_source']}")
    print(f"최근 {hours}h 이내   : {rep['within_%dh' % hours]}")
    print(f"중복 canonical군 : {rep['duplicate_canonical_groups']} (s2 dedup L1 예상)")
    print("-" * 64)
    print("필드 누락(빈 값 포함):")
    for f, n in rep["field_missing"].items():
        note = "  ← 네이버는 outlet 미제공(정상)" if f == "outlet" else ""
        print(f"  {f:14}: {n}{note}")
    print(f"필수필드 결손 기사: {rep['required_broken_count']}")
    for s in rep["required_broken_samples"]:
        print(f"    - missing {s['missing']}  {s['url']}")
    print("-" * 64)
    print(f"인코딩 이상 기사  : {rep['encoding_issue_count']}")
    for s in rep["encoding_issue_samples"]:
        print(f"    - {s['issues']}  «{s['title']}»")
    if rep["source_errors"]:
        print("-" * 64)
        print(f"소스 오류(fail-soft): {len(rep['source_errors'])}")
        for e in rep["source_errors"][:5]:
            print(f"    - {e.get('source')}/{e.get('query','')}: {e.get('reason')}")
    print(line)
    verdict = "PASS" if rep["required_broken_count"] == 0 and rep["encoding_issue_count"] == 0 else "CHECK"
    print(f"판정: {verdict}  (필수필드 결손·인코딩 이상 0 이면 PASS)")
    print(line)


def main() -> None:
    ap = argparse.ArgumentParser(description="Z2 실데이터 스모크 — s1_collect 검증")
    ap.add_argument("--track", default="posco")
    ap.add_argument("--category", default="futurem")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--no-naver", action="store_true")
    ap.add_argument("--max-queries", type=int, default=None,
                    help="쿼리 수 상한 (기본: 해당 카테고리 must 전체)")
    args = ap.parse_args()

    s1_collect._load_dotenv(common.ROOT / ".env")
    keywords = common.load_keywords()
    now = common.now_kst()

    records, errors = s1_collect.collect(
        keywords,
        use_naver=not args.no_naver,
        naver_id=os.environ.get("NAVER_CLIENT_ID"),
        naver_secret=os.environ.get("NAVER_CLIENT_SECRET"),
        max_queries=args.max_queries,
        only_tracks=[args.track],
        only_categories=[args.category],
    )

    # 1) 원본 응답 → cache/smoke/ (gitignore, 커밋 안 됨) — 운영자 디버깅용
    cache_dir = common.ROOT / "cache" / "smoke"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"raw-{args.track}-{args.category}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8"
    )

    # 2) fixture → tests/fixtures/ (커밋 대상) — 메타데이터 + 200자 발췌만 (INV-5)
    fx_dir = common.ROOT / "tests" / "fixtures"
    fx_dir.mkdir(parents=True, exist_ok=True)
    samples = [sanitize(r) for r in records[:MAX_FIXTURE_SAMPLES]]
    fixture = {
        "generated_at": now.isoformat(),
        "track": args.track,
        "category": args.category,
        "window_hours": args.hours,
        "excerpt_limit": EXCERPT_LIMIT,
        "note": "INV-5: 본문 전문 없음. 메타데이터 + 200자 이내 발췌만.",
        "sample_count": len(samples),
        "samples": samples,
    }
    fx_path = fx_dir / f"collect_{args.track}_{args.category}.sample.json"
    fx_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")

    rep = report(records, errors, args.hours, now)
    print_report(rep, args.hours)
    print(f"원본(비커밋)  : {cache_dir}/raw-{args.track}-{args.category}.jsonl")
    print(f"fixture(커밋) : {fx_path}  (samples={len(samples)}, 발췌≤{EXCERPT_LIMIT}자)")


if __name__ == "__main__":
    main()
