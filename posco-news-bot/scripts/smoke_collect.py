#!/usr/bin/env python3
"""Z2 실데이터 스모크 — s1_collect 만 실행해 실제 RSS 응답을 검증한다.

목적: 합성 fixture 로는 못 잡는 ★매체별 RSS 포맷 편차★를 확인한다.
      (날짜 포맷·description 유무·CDATA/HTML 태그·인코딩·링크 형태)

동작:
  1. rss_sources.yaml 의 활성 피드를 실제로 받아온다 (1순위)
  2. 피드별 파싱 편차 리포트 — 날짜 파싱 실패율·설명 결손율·태그 잔존
  3. keywords.yaml 필터 통과율 (피드 전체 → 우리 관심사)
  4. 원본 응답은 cache/smoke/ 에 저장 (.gitignore — 커밋 안 됨)
  5. tests/fixtures/ 에는 ★메타데이터 + 200자 이내 발췌만★ 저장 (INV-5)

사용:
  cd posco-news-bot
  python -m scripts.smoke_collect                    # 활성 RSS 전체
  python -m scripts.smoke_collect --feed yonhap-economy   # 피드 1개만
  python -m scripts.smoke_collect --with-google      # 구글 보조까지 함께
  python -m scripts.smoke_collect --hours 48
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from pipeline.stages import common, rss, s1_collect

EXCERPT_LIMIT = 200  # INV-5: 발췌 상한 (본문 전문 금지)
MAX_FIXTURE_SAMPLES = 30

REQUIRED_FIELDS = ["title", "url"]                     # 없으면 기사로 성립 안 함
REPORT_FIELDS = ["title", "url", "published_at", "outlet", "description", "categories"]

_REPLACEMENT = "�"                                    # 깨진 문자
_LEFTOVER_ENTITY = re.compile(r"&(?:amp|lt|gt|quot|#\d+|#x[0-9a-fA-F]+);")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_LEFTOVER_TAG = re.compile(r"<[^>]+>")
_LEFTOVER_CDATA = re.compile(r"<!\[CDATA\[|\]\]>")


def excerpt(text: str | None) -> str:
    """INV-5: 200자 이내 발췌."""
    return common.collapse_ws(text or "")[:EXCERPT_LIMIT]


def sanitize(rec: dict[str, Any]) -> dict[str, Any]:
    """fixture 저장용 — 본문 전문 없이 메타데이터 + 발췌만."""
    return {
        "title": rec.get("title"),
        "url": rec.get("url"),
        "outlet": rec.get("outlet"),
        "published_at": rec.get("published_at"),
        "source": rec.get("source"),
        "source_id": rec.get("source_id"),
        "lang": rec.get("lang"),
        "track": rec.get("track"),
        "category": rec.get("category"),
        "categories": rec.get("categories"),
        "excerpt": excerpt(rec.get("description")),
    }


def within_hours(rec: dict[str, Any], hours: int, now) -> bool:
    pub = common.parse_dt(rec.get("published_at"))
    if pub is None:
        return True  # 시각 미상은 포함하되 별도 카운트
    return (now - pub).total_seconds() <= hours * 3600


def find_text_issues(rec: dict[str, Any]) -> list[str]:
    """정규화 계층이 흡수했어야 할 잔존물 탐지."""
    issues: list[str] = []
    for field in ("title", "description"):
        val = rec.get(field) or ""
        if _REPLACEMENT in val:
            issues.append(f"{field}: U+FFFD 치환문자(인코딩)")
        if _LEFTOVER_ENTITY.search(val):
            issues.append(f"{field}: 미복원 HTML 엔티티")
        if _LEFTOVER_TAG.search(val):
            issues.append(f"{field}: HTML 태그 잔존")
        if _LEFTOVER_CDATA.search(val):
            issues.append(f"{field}: CDATA 마커 잔존")
        if _CONTROL.search(val):
            issues.append(f"{field}: 제어문자")
        if val and unicodedata.normalize("NFC", val) != val:
            issues.append(f"{field}: 유니코드 정규화(NFC) 불일치")
    return issues


def feed_report(feed_id: str, name: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    """★매체별 파싱 편차★ — 이 표가 이 스모크의 본체다."""
    n = len(items)
    no_date = sum(1 for r in items if not r.get("published_at"))
    no_desc = sum(1 for r in items if not (r.get("description") or "").strip())
    no_link = sum(1 for r in items if not (r.get("url") or "").strip())
    no_cat = sum(1 for r in items if not r.get("categories"))
    issues = sum(1 for r in items if find_text_issues(r))
    samples = [r.get("published_at") for r in items[:3]]
    return {
        "feed": feed_id, "outlet": name, "items": n,
        "date_missing": no_date, "desc_missing": no_desc,
        "link_missing": no_link, "category_missing": no_cat,
        "text_issue": issues, "date_samples": samples,
    }


def print_feed_table(rows: list[dict[str, Any]]) -> None:
    print("-" * 78)
    print("매체별 파싱 편차 (결손은 정상일 수 있으나 100% 결손은 파서 점검 대상)")
    print(f"  {'feed':22} {'건수':>4} {'날짜X':>5} {'설명X':>5} {'링크X':>5} {'분류X':>5} {'이상':>4}")
    for r in rows:
        print(f"  {r['feed'][:22]:22} {r['items']:>4} {r['date_missing']:>5} "
              f"{r['desc_missing']:>5} {r['link_missing']:>5} {r['category_missing']:>5} {r['text_issue']:>4}")
    for r in rows:
        if r["items"] and r["date_missing"] == r["items"]:
            print(f"  ⚠️ {r['feed']}: 날짜 전량 파싱 실패 → 샘플 {r['date_samples']} 포맷 추가 필요")
        if r["items"] == 0:
            print(f"  ⚠️ {r['feed']}: 0건 — URL 오류·차단·빈 피드 중 하나")
        if r["items"] and r["link_missing"]:
            print(f"  ⚠️ {r['feed']}: 링크 결손 {r['link_missing']}건 → <link> 형태 확인")


def print_report(rep: dict[str, Any], hours: int) -> None:
    line = "=" * 78
    print(line)
    print("실데이터 스모크 리포트 (s1_collect · RSS 1순위)")
    print(line)
    print(f"피드 원본 총건수  : {rep['raw_total']}")
    print(f"키워드 통과       : {rep['kept_total']}  (제외 {rep['dropped_total']})")
    print(f"소스별            : {rep['by_source']}")
    print(f"최근 {hours}h 이내    : {rep['recent']}  (시각 미상 {rep['no_date']}건 포함)")
    print(f"중복 canonical군  : {rep['duplicate_canonical_groups']} (s2 dedup L1 예상)")
    print_feed_table(rep["feeds"])
    print("-" * 78)
    print(f"필수필드(title·url) 결손: {rep['required_broken_count']}")
    for s in rep["required_broken_samples"]:
        print(f"    - missing {s['missing']}  {s['title']}")
    print(f"텍스트/인코딩 이상       : {rep['text_issue_count']}")
    for s in rep["text_issue_samples"]:
        print(f"    - {s['issues']}  «{s['title']}»")
    if rep["errors"]:
        print("-" * 78)
        print(f"소스 오류·메모(fail-soft): {len(rep['errors'])}")
        for e in rep["errors"][:8]:
            print(f"    - {e.get('source')}/{e.get('feed', e.get('query',''))}: {e.get('reason')}")
    cov = rep.get("coverage") or {}
    if cov.get("unregistered_outlets"):
        print("-" * 78)
        print(f"RSS 미등록 매체 후보(구글로만 잡힘): {list(cov['unregistered_outlets'])[:10]}")
    print(line)
    verdict = "PASS" if (rep["required_broken_count"] == 0 and rep["text_issue_count"] == 0
                         and rep["raw_total"] > 0) else "CHECK"
    print(f"판정: {verdict}  (원본>0 · 필수필드 결손 0 · 텍스트 이상 0 이면 PASS)")
    print(line)


def main() -> None:
    ap = argparse.ArgumentParser(description="Z2 실데이터 스모크 — RSS 파싱 편차 검증")
    ap.add_argument("--feed", default=None, help="피드 id 1개만 (기본: 활성 전체)")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--with-google", action="store_true", help="구글 보조까지 함께 확인")
    ap.add_argument("--max-queries", type=int, default=5, help="구글 쿼리 상한")
    args = ap.parse_args()

    s1_collect._load_dotenv(common.ROOT / ".env")
    keywords = common.load_keywords()
    now = common.now_kst()

    cfg = rss.load_sources()
    if args.feed:
        cfg = {**cfg, "sources": [s for s in cfg["sources"] if s.get("id") == args.feed]}
        if not cfg["sources"]:
            raise SystemExit(f"rss_sources.yaml 에 id={args.feed} 없음")

    # ① 피드 원본 (필터 전) — 파싱 편차는 필터 전 상태에서 봐야 한다
    raw_items, feed_errors, feed_counts = rss.collect_feeds(cfg)
    by_feed: dict[str, list[dict[str, Any]]] = {}
    for r in raw_items:
        by_feed.setdefault(r.get("source_id") or "?", []).append(r)
    names = {s["id"]: s.get("name", s["id"]) for s in cfg["sources"] if s.get("id")}
    feeds = [feed_report(fid, names.get(fid, fid), by_feed.get(fid, []))
             for fid in [s["id"] for s in rss.enabled_sources(cfg)]]

    # ② 필터 후 (실제로 파이프라인에 들어가는 것) + 커버리지
    records, errors, coverage = s1_collect.collect(
        keywords, use_rss=True, use_google=args.with_google, use_naver_hub=False,
        rss_cfg=cfg, max_queries=args.max_queries, track_health=False,
    )
    kept_rss = [r for r in records if r.get("source") == "rss"]

    canon: dict[str, int] = {}
    for r in records:
        c = common.canonical_url(r.get("url") or "")
        canon[c] = canon.get(c, 0) + 1

    required_broken = [
        {"title": excerpt(r.get("title"))[:50],
         "missing": [f for f in REQUIRED_FIELDS if not (r.get(f) and str(r.get(f)).strip())]}
        for r in raw_items
        if any(not (r.get(f) and str(r.get(f)).strip()) for f in REQUIRED_FIELDS)
    ]
    text_hits = [{"title": excerpt(r.get("title"))[:60], "issues": iss}
                 for r in raw_items if (iss := find_text_issues(r))]

    rep = {
        "raw_total": len(raw_items),
        "kept_total": len(kept_rss),
        "dropped_total": len(raw_items) - len(kept_rss),
        "by_source": coverage.get("by_source", {}),
        "recent": sum(1 for r in records if within_hours(r, args.hours, now)),
        "no_date": sum(1 for r in records if not r.get("published_at")),
        "duplicate_canonical_groups": sum(1 for n in canon.values() if n > 1),
        "feeds": feeds,
        "feed_counts": feed_counts,
        "required_broken_count": len(required_broken),
        "required_broken_samples": required_broken[:5],
        "text_issue_count": len(text_hits),
        "text_issue_samples": text_hits[:5],
        "errors": feed_errors + errors,
        "coverage": coverage,
    }
    print_report(rep, args.hours)

    # 원본 → cache/smoke/ (gitignore) — 운영자 디버깅용
    cache_dir = common.ROOT / "cache" / "smoke"
    cache_dir.mkdir(parents=True, exist_ok=True)
    raw_path = cache_dir / f"raw-rss-{args.feed or 'all'}.jsonl"
    raw_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in raw_items),
                        encoding="utf-8")
    (cache_dir / "smoke-report.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    # fixture → tests/fixtures/ (커밋 대상) — 메타데이터 + 200자 발췌만 (INV-5)
    fx_dir = common.ROOT / "tests" / "fixtures"
    fx_dir.mkdir(parents=True, exist_ok=True)
    samples = [sanitize(r) for r in records[:MAX_FIXTURE_SAMPLES]]
    fixture = {
        "generated_at": now.isoformat(),
        "source": "rss",
        "feeds": [s["id"] for s in rss.enabled_sources(cfg)],
        "window_hours": args.hours,
        "excerpt_limit": EXCERPT_LIMIT,
        "note": "INV-5: 본문 전문 없음. 메타데이터 + 200자 이내 발췌만.",
        "sample_count": len(samples),
        "samples": samples,
    }
    fx_path = fx_dir / f"collect_rss_{args.feed or 'all'}.sample.json"
    fx_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"원본(비커밋)  : {raw_path}")
    print(f"fixture(커밋) : {fx_path}  (samples={len(samples)}, 발췌≤{EXCERPT_LIMIT}자)")


if __name__ == "__main__":
    main()
