"""s1_collect — 뉴스 수집기.

소스:
  - 네이버 검색 API (국문). NAVER_CLIENT_ID/SECRET 가 .env 에 있을 때만.
    ⚠️ 키가 없으면 네이버를 건너뛰고 구글 RSS 만으로 동작한다 (fail-soft).
  - 구글 뉴스 RSS (ko / en). 트랙 언어(track_lang)에 따라 en 포함.
    · T1 posco / T2 battery → ko 만
    · T3 policy / T4 trade  → ko + en

출력: raw/<run_id>/collected.jsonl  (s2_normalize 입력)

건별/소스별 실패는 errors[] 에 기록하고 계속한다 (스테이지 전체 실패만 중단).
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from . import common

USER_AGENT = "posco-news-bot/0.1 (+https://github.com/taehyun108/kth_05)"
HTTP_TIMEOUT = 15
NAVER_ENDPOINT = "https://openapi.naver.com/v1/search/news.json"
GOOGLE_RSS = "https://news.google.com/rss/search"

GOOGLE_LOCALE = {
    "ko": {"hl": "ko", "gl": "KR", "ceid": "KR:ko"},
    "en": {"hl": "en", "gl": "US", "ceid": "US:en"},
}

_TAG = re.compile(r"<[^>]+>")


def _clean(text: str | None) -> str:
    return common.collapse_ws(html.unescape(_TAG.sub("", text or "")))


def _load_dotenv(path: Path) -> None:
    """의존성 없이 .env 를 os.environ 에 로드 (이미 설정된 값은 덮어쓰지 않음)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


def _http_get(url: str, headers: dict[str, str] | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read()


# ── 소스별 수집 ──────────────────────────────────────────────────────────

def naver_search(query: str, client_id: str, client_secret: str, display: int = 100) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"query": query, "display": display, "sort": "date"})
    raw = _http_get(
        f"{NAVER_ENDPOINT}?{params}",
        headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret},
    )
    data = json.loads(raw)
    out: list[dict[str, Any]] = []
    for item in data.get("items", []):
        link = item.get("originallink") or item.get("link") or ""
        pub = item.get("pubDate")
        pub_iso = None
        if pub:
            try:
                pub_iso = parsedate_to_datetime(pub).astimezone(common.KST).isoformat()
            except (TypeError, ValueError):
                pub_iso = None
        out.append({
            "title": _clean(item.get("title")),
            "url": link,
            "outlet": None,  # 네이버 API 는 매체명을 주지 않는다 (도메인 추론은 P2)
            "published_at": pub_iso,
            "description": _clean(item.get("description")),
            "source": "naver",
            "source_type": "news",
        })
    return out


def google_news_rss(query: str, lang: str) -> list[dict[str, Any]]:
    loc = GOOGLE_LOCALE.get(lang, GOOGLE_LOCALE["ko"])
    params = urllib.parse.urlencode({"q": query, **loc})
    raw = _http_get(f"{GOOGLE_RSS}?{params}")
    root = ET.fromstring(raw)
    out: list[dict[str, Any]] = []
    for item in root.iterfind(".//item"):
        title = _clean(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        pub = item.findtext("pubDate")
        pub_iso = None
        if pub:
            try:
                pub_iso = parsedate_to_datetime(pub).astimezone(common.KST).isoformat()
            except (TypeError, ValueError):
                pub_iso = None
        source_el = item.find("source")
        outlet = _clean(source_el.text) if source_el is not None else None
        out.append({
            "title": title,
            "url": link,
            "outlet": outlet,
            "published_at": pub_iso,
            "description": _clean(item.findtext("description")),
            "source": "google",
            "source_type": "news",
            "lang": lang,
        })
    return out


# ── 수집 계획 ────────────────────────────────────────────────────────────

def build_plan(
    keywords: dict[str, Any],
    only_tracks: list[str] | None = None,
    only_categories: list[str] | None = None,
) -> list[dict[str, Any]]:
    """(track, category, keyword, lang) 쿼리 계획. must 키워드만 쿼리로 사용.

    only_tracks / only_categories 로 스모크·부분 수집 범위를 좁힐 수 있다.
    """
    plan: list[dict[str, Any]] = []
    tracks = keywords.get("tracks") or {}
    for track, cats in tracks.items():
        if only_tracks and track not in only_tracks:
            continue
        for category, cfg in cats.items():
            if only_categories and category not in only_categories:
                continue
            langs = common.track_langs(keywords, track, cfg)
            for kw in cfg.get("must") or []:
                for lang in langs:
                    plan.append({"track": track, "category": category, "keyword": kw, "lang": lang})
    return plan


def collect(
    keywords: dict[str, Any],
    *,
    use_naver: bool = True,
    naver_id: str | None = None,
    naver_secret: str | None = None,
    max_queries: int | None = None,
    only_tracks: list[str] | None = None,
    only_categories: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """계획을 실행해 원시 레코드와 errors 를 반환. 소스 실패는 fail-soft."""
    plan = build_plan(keywords, only_tracks=only_tracks, only_categories=only_categories)
    if max_queries:
        plan = plan[:max_queries]

    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    naver_ok = bool(use_naver and naver_id and naver_secret)
    if use_naver and not naver_ok:
        errors.append({"stage": "collect", "source": "naver",
                       "reason": "NAVER_CLIENT_ID/SECRET 미설정 — 구글 RSS 만으로 진행 (fail-soft)"})

    def tag(recs: list[dict[str, Any]], item: dict[str, Any]) -> list[dict[str, Any]]:
        for r in recs:
            r.setdefault("track", item["track"])
            r.setdefault("category", item["category"])
            r.setdefault("lang", item["lang"])
        return recs

    for item in plan:
        # 구글 뉴스 RSS
        try:
            records.extend(tag(google_news_rss(item["keyword"], item["lang"]), item))
        except (urllib.error.URLError, ET.ParseError, ValueError) as exc:
            errors.append({"stage": "collect", "source": "google", "query": item["keyword"],
                           "lang": item["lang"], "reason": repr(exc)})
        # 네이버 (국문 쿼리에만)
        if naver_ok and item["lang"] == "ko":
            try:
                records.extend(tag(naver_search(item["keyword"], naver_id, naver_secret), item))
            except (urllib.error.URLError, ValueError) as exc:
                errors.append({"stage": "collect", "source": "naver", "query": item["keyword"],
                               "reason": repr(exc)})
    return records, errors


# ── CLI ──────────────────────────────────────────────────────────────────

def run(
    run_id: str | None = None,
    base_dir: Path | None = None,
    keywords_path: Path | None = None,
    *,
    use_naver: bool = True,
    max_queries: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    _load_dotenv(common.ROOT / ".env")
    keywords = common.load_keywords(keywords_path)
    run_id = run_id or common.make_run_id()
    base = base_dir or (common.ROOT / "raw")

    if dry_run:
        plan = build_plan(keywords)
        if max_queries:
            plan = plan[:max_queries]
        print(f"[s1] dry-run: {len(plan)} queries planned, run_id={run_id}")
        langs = sorted({(p['track'], p['lang']) for p in plan})
        print(f"[s1] track/lang pairs: {langs}")
        return {"plan": plan, "run_id": run_id}

    records, errors = collect(
        keywords,
        use_naver=use_naver,
        naver_id=os.environ.get("NAVER_CLIENT_ID"),
        naver_secret=os.environ.get("NAVER_CLIENT_SECRET"),
        max_queries=max_queries,
    )
    out_path = base / run_id / "collected.jsonl"
    n = common.write_jsonl(out_path, records)
    (base / run_id / "collected.errors.json").write_text(
        json.dumps(errors, ensure_ascii=False, indent=2)
    )
    print(f"[s1] collected {n} raw records → {out_path}")
    if errors:
        print(f"[s1] {len(errors)} source errors (fail-soft, 기록 후 계속)")
    return {"records": records, "errors": errors, "run_id": run_id, "out_path": str(out_path)}


def main() -> None:
    ap = argparse.ArgumentParser(description="s1_collect — 4트랙 뉴스 수집")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--base-dir", default=None)
    ap.add_argument("--no-naver", action="store_true", help="네이버 API 강제 비활성")
    ap.add_argument("--max-queries", type=int, default=None, help="쿼리 수 상한(테스트용)")
    ap.add_argument("--dry-run", action="store_true", help="네트워크 없이 수집 계획만 출력")
    args = ap.parse_args()
    run(
        run_id=args.run_id,
        base_dir=Path(args.base_dir) if args.base_dir else None,
        use_naver=not args.no_naver,
        max_queries=args.max_queries,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
