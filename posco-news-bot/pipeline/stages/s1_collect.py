"""s1_collect — 뉴스 수집기 (2026-09 소스 재설계).

소스 우선순위:
  1순위 ★언론사 RSS 직접 구독★ (rss_sources.yaml) — 질의가 아니라 피드 전체를 받아
        keywords.yaml 의 must 키워드(+posco_entities)로 걸러낸다. 원문 URL 이 그대로 온다.
  2순위 구글 뉴스 RSS — 1순위가 못 잡는 것을 메우는 보조. 차단 시 fail-soft + 운영 알림.
  (비활성) 네이버 — 검색 API 가 NAVER API HUB 로 이관(2026-07 신규신청 종료)되어
        결제수단 등록이 필요해 쓰지 않는다. 어댑터만 남기고 기본 비활성.

출력: raw/<run_id>/collected.jsonl  (s2_normalize 입력)
개별 피드/소스 실패는 errors[] 에 기록하고 계속. ★전 소스 실패 시에만 중단★.

커버리지: RSS 는 등록한 매체만 본다 → 매체별 건수·죽은 피드·미등록 매체 후보를
         coverage 로 반환하고 S8 리포트가 노출한다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from . import common, rss

USER_AGENT = rss.USER_AGENT
HTTP_TIMEOUT = 15
GOOGLE_RSS = "https://news.google.com/rss/search"

# 네이버 API HUB (2026-06 이관) — 결제수단 필요로 기본 비활성. env 채우면 켜진다.
NAVER_HUB_HOST = "https://naverapihub.apigw.ntruss.com"
NAVER_HUB_PATH = "/search/v1/news"

GOOGLE_LOCALE = {
    "ko": {"hl": "ko", "gl": "KR", "ceid": "KR:ko"},
    "en": {"hl": "en", "gl": "US", "ceid": "US:en"},
}

DEAD_FEED_DAYS = 3          # 연속 0건이 이 횟수 이상이면 '죽은 피드 의심'
STALE_FEED_DAYS = 14        # ★200 이 와도 최신 기사가 이보다 오래면 '정체된 피드'★
                            # (2026-09-01 전자신문 06064 소재 피드가 68일 정체 상태로 확인됨)


def _clean(text: str | None) -> str:
    return rss.clean_text(text)


def _load_dotenv(path: Path) -> None:
    """의존성 없이 .env 를 os.environ 에 로드 (이미 설정된 값은 덮어쓰지 않음)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _http_get(url: str, headers: dict[str, str] | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read()


# ── 키워드 매칭 (RSS 필터 게이트) ────────────────────────────────────────────

_WS_ALL = re.compile(r"\s+")


def _squash(text: str) -> str:
    """공백 제거 + 소문자화. ★띄어쓰기 변형 흡수용★

    한국어 기사는 같은 개념을 띄어쓰기만 바꿔 쓴다:
      '음극 소재' · '음극소재' / '양극 활물질' · '양극활물질' / '건식 기반 음극' …
    사전에 모든 변형을 넣는 대신, 양쪽에서 공백을 지우고 비교한다.

    부작용: 단어 경계를 넘어 붙는 오탐이 생길 수 있다('음극 재활용'→'음극재활용' ⊃ '음극재').
    이 도메인에서는 그 오탐도 대개 배터리 소재 기사라 수용 가능하다고 판단했다.
    최종 판정이 아니라 ★수집 후보 선별★ 단계라는 점도 근거다(하류 prescore·dedup 이 더 거른다).
    """
    return _WS_ALL.sub("", (text or "")).lower()


def _contains(text_low: str, text_squashed: str, kw: str) -> bool:
    """원문 그대로 / 공백 제거본 둘 중 하나라도 걸리면 히트."""
    if not kw:
        return False
    k = kw.lower()
    return k in text_low or _squash(kw) in text_squashed


def match_keywords(text: str, keywords: dict[str, Any]) -> list[tuple[str, str]]:
    """텍스트가 어느 (track, category) 에 걸리는지. must 키워드가 게이트다.

    질의 기반 수집과 동일한 기준을 유지하려고 must 만 본다(expand 는 prescore 에서).
    추가로 posco_entities 에 걸리면 posco 트랙으로 편입한다 — 카톡 게이트 커버리지 보호.
    매칭은 원문과 공백 제거본 양쪽으로 본다(_squash).
    """
    low = (text or "").lower()
    squashed = _squash(text)
    hits: list[tuple[str, str]] = []
    for track, cats in (keywords.get("tracks") or {}).items():
        for category, cfg in (cats or {}).items():
            for kw in cfg.get("must") or []:
                if _contains(low, squashed, kw):
                    hits.append((track, category))
                    break
    if not any(t == "posco" for t, _ in hits):
        for aliases in (keywords.get("posco_entities") or {}).values():
            if any(_contains(low, squashed, a) for a in aliases):
                hits.append(("posco", "group"))
                break
    return hits


def filter_rss_records(records: list[dict[str, Any]], keywords: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """피드 전체에서 키워드에 걸리는 것만 남기고 track/category 를 태깅."""
    kept: list[dict[str, Any]] = []
    dropped = 0
    for r in records:
        text = f"{r.get('title','')} {r.get('description','')} {' '.join(r.get('categories') or [])}"
        hits = match_keywords(text, keywords)
        if not hits:
            dropped += 1
            continue
        track, category = hits[0]
        r = dict(r)
        r["track"] = track
        r["category"] = category
        if len(hits) > 1:
            r["also_tracks"] = sorted({t for t, _ in hits[1:]} - {track})
        kept.append(r)
    return kept, dropped


# ── 2순위: 구글 뉴스 RSS (질의 기반 보조) ───────────────────────────────────

def google_news_rss(query: str, lang: str) -> list[dict[str, Any]]:
    loc = GOOGLE_LOCALE.get(lang, GOOGLE_LOCALE["ko"])
    params = urllib.parse.urlencode({"q": query, **loc})
    raw = _http_get(f"{GOOGLE_RSS}?{params}")
    items = rss.parse_items(raw, {"lang": lang, "source_type": "news"})
    out = []
    for it in items:
        el_outlet = it.get("outlet")
        out.append({**it, "source": "google", "outlet": el_outlet})
    return out


def _google_outlets(xml_bytes: bytes) -> list[str]:
    """구글 RSS 의 <source> 매체명 (미등록 매체 후보 집계용)."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    return [rss.clean_text(s.text) for s in root.iterfind(".//item/source") if (s.text or "").strip()]


def build_plan(
    keywords: dict[str, Any],
    only_tracks: list[str] | None = None,
    only_categories: list[str] | None = None,
) -> list[dict[str, Any]]:
    """구글 보조 수집용 (track, category, keyword, lang) 쿼리 계획."""
    plan: list[dict[str, Any]] = []
    for track, cats in (keywords.get("tracks") or {}).items():
        if only_tracks and track not in only_tracks:
            continue
        for category, cfg in (cats or {}).items():
            if only_categories and category not in only_categories:
                continue
            for kw in cfg.get("must") or []:
                for lang in common.track_langs(keywords, track, cfg):
                    plan.append({"track": track, "category": category, "keyword": kw, "lang": lang})
    return plan


# ── (비활성) 네이버 API HUB 어댑터 ───────────────────────────────────────────

def naver_hub_enabled() -> bool:
    return bool(os.environ.get("NAVER_HUB_KEY_ID") and os.environ.get("NAVER_HUB_KEY"))


def naver_hub_search(query: str, display: int = 100) -> list[dict[str, Any]]:
    """NAVER API HUB 뉴스 검색. env(NAVER_HUB_KEY_ID/NAVER_HUB_KEY) 있을 때만 호출된다.

    ⚠️ 네이버클라우드 계정+결제수단이 필요해 현재 미사용. 구조만 유지한다.
    """
    params = urllib.parse.urlencode({"query": query, "display": display, "sort": "date"})
    raw = _http_get(f"{NAVER_HUB_HOST}{NAVER_HUB_PATH}?{params}", headers={
        "X-NCP-APIGW-API-KEY-ID": os.environ.get("NAVER_HUB_KEY_ID", ""),
        "X-NCP-APIGW-API-KEY": os.environ.get("NAVER_HUB_KEY", ""),
    })
    data = json.loads(raw)
    out: list[dict[str, Any]] = []
    for item in data.get("items", []):
        pub = item.get("pubDate")
        try:
            pub_iso = parsedate_to_datetime(pub).astimezone(common.KST).isoformat() if pub else None
        except (TypeError, ValueError):
            pub_iso = None
        out.append({
            "title": _clean(item.get("title")),
            "url": item.get("originallink") or item.get("link") or "",
            "outlet": None,
            "published_at": pub_iso,
            "description": _clean(item.get("description")),
            "source": "naver_hub",
            "source_type": "news",
        })
    return out


# ── 커버리지 / 피드 건강 ─────────────────────────────────────────────────────

def feed_health_path() -> Path:
    return common.state_dir() / "feed_health.json"


def update_feed_health(counts: dict[str, int], now_iso: str | None = None) -> dict[str, Any]:
    """피드별 연속 0건 횟수를 누적. 죽은 피드 의심 판정에 쓴다."""
    p = feed_health_path()
    health: dict[str, Any] = {}
    if p.exists():
        try:
            health = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            health = {}
    now_iso = now_iso or common.now_kst().isoformat()
    for fid, n in counts.items():
        rec = health.get(fid) or {"consecutive_zero": 0, "last_count": 0, "last_seen": None}
        rec["last_count"] = n
        if n > 0:
            rec["consecutive_zero"] = 0
            rec["last_seen"] = now_iso
        else:
            rec["consecutive_zero"] = int(rec.get("consecutive_zero", 0)) + 1
        health[fid] = rec
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(health, ensure_ascii=False, indent=2), encoding="utf-8")
    return health


def dead_feeds(health: dict[str, Any], threshold: int = DEAD_FEED_DAYS) -> list[str]:
    return sorted(f for f, r in health.items() if int(r.get("consecutive_zero", 0)) >= threshold)


def feed_freshness(raw_items: list[dict[str, Any]]) -> dict[str, str]:
    """피드별 ★최신 기사 발행시각★. 건수만으로는 정체를 못 잡는다."""
    newest: dict[str, str] = {}
    for r in raw_items:
        fid, pub = r.get("source_id"), r.get("published_at")
        if not fid or not pub:
            continue
        if fid not in newest or pub > newest[fid]:
            newest[fid] = pub
    return newest


def stale_thresholds(cfg: dict[str, Any] | None) -> dict[str, int]:
    """피드별 stale_days. 미지정이면 기본 STALE_FEED_DAYS.

    주간 단위로 갱신되는 섹션 피드가 있어서 14일 일괄 기준은 정상 피드를 오탐한다.
    → rss_sources.yaml 에서 피드마다 stale_days 를 따로 준다.
    """
    out: dict[str, int] = {}
    for src in (cfg or {}).get("sources", []) or []:
        fid = src.get("id")
        if fid and src.get("stale_days"):
            out[fid] = int(src["stale_days"])
    return out


def feed_age_days(freshness: dict[str, str], now: Any = None) -> dict[str, int]:
    """피드별 최신 기사 경과일. 판정과 무관하게 리포트에 항상 싣는다(추세 관찰용)."""
    now = now or common.now_kst()
    out: dict[str, int] = {}
    for fid, iso in freshness.items():
        dt = common.parse_dt(iso)
        if dt is not None:
            out[fid] = (now - dt).days
    return out


def stale_feeds(freshness: dict[str, str], threshold_days: int = STALE_FEED_DAYS,
                now: Any = None, thresholds: dict[str, int] | None = None) -> dict[str, int]:
    """200 은 오지만 갱신이 멈춘 피드 → {feed_id: 경과일}.

    ★죽은 피드(0건)와 다른 고장 모드다.★ 기사를 가득 주지만 전부 과거 것이라
    건수 기반 감시로는 영원히 안 잡힌다. 실제로 전자신문 소재 피드가 이 상태였다.
    임계는 피드별(stale_days) → 없으면 threshold_days.
    """
    ages = feed_age_days(freshness, now)
    per = thresholds or {}
    out = {fid: age for fid, age in ages.items() if age >= per.get(fid, threshold_days)}
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def build_coverage(records: list[dict[str, Any]], feed_counts: dict[str, int],
                   registered_outlets: set[str], health: dict[str, Any] | None = None,
                   freshness: dict[str, str] | None = None,
                   thresholds: dict[str, int] | None = None) -> dict[str, Any]:
    """매체별 건수 · 소스별 건수 · 죽은 피드 · 정체 피드 · RSS 미등록 매체 후보."""
    by_outlet: dict[str, int] = {}
    by_source: dict[str, int] = {}
    google_outlets: dict[str, int] = {}
    for r in records:
        outlet = r.get("outlet") or "(미상)"
        by_outlet[outlet] = by_outlet.get(outlet, 0) + 1
        src = r.get("source", "?")
        by_source[src] = by_source.get(src, 0) + 1
        if src == "google" and r.get("outlet"):
            google_outlets[r["outlet"]] = google_outlets.get(r["outlet"], 0) + 1
    # 구글로만 잡힌 매체 = RSS 등록 후보
    unregistered = {o: n for o, n in google_outlets.items() if o not in registered_outlets}
    return {
        "by_outlet": dict(sorted(by_outlet.items(), key=lambda kv: -kv[1])),
        "by_source": by_source,
        "feed_counts": feed_counts,
        "dead_feeds": dead_feeds(health or {}),
        "feed_newest": freshness or {},
        "feed_age_days": feed_age_days(freshness or {}),
        "stale_feeds": stale_feeds(freshness or {}, thresholds=thresholds),
        "stale_thresholds": thresholds or {},
        "unregistered_outlets": dict(sorted(unregistered.items(), key=lambda kv: -kv[1])),
    }


# ── 수집 실행 ────────────────────────────────────────────────────────────────

def collect(
    keywords: dict[str, Any],
    *,
    use_rss: bool = True,
    use_google: bool = True,
    use_naver_hub: bool | None = None,
    rss_cfg: dict[str, Any] | None = None,
    rss_fetcher=None,
    max_queries: int | None = None,
    only_tracks: list[str] | None = None,
    only_categories: list[str] | None = None,
    track_health: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """전 소스 수집. 반환: (records, errors, coverage). 개별 실패는 fail-soft."""
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    feed_counts: dict[str, int] = {}
    freshness: dict[str, str] = {}
    rss_cfg_used: dict[str, Any] | None = None
    registered: set[str] = set()
    source_ok = 0
    source_tried = 0

    # ── 1순위: 언론사 RSS ──
    if use_rss:
        source_tried += 1
        cfg = rss_cfg if rss_cfg is not None else rss.load_sources()
        rss_cfg_used = cfg
        registered = {s.get("name") for s in cfg.get("sources", []) if s.get("name")}
        raw_items, rss_errors, feed_counts = rss.collect_feeds(cfg, rss_fetcher)
        freshness = feed_freshness(raw_items)
        errors.extend(rss_errors)
        kept, dropped = filter_rss_records(raw_items, keywords)
        records.extend(kept)
        if kept or not rss_errors:
            source_ok += 1
        errors.append({"stage": "collect", "source": "rss", "level": "info",
                       "reason": f"피드 {len(feed_counts)}개 · 원본 {len(raw_items)} → 키워드 통과 {len(kept)} (제외 {dropped})"})

    # ── 2순위: 구글 뉴스 RSS (보조) ──
    if use_google:
        source_tried += 1
        plan = build_plan(keywords, only_tracks=only_tracks, only_categories=only_categories)
        if max_queries:
            plan = plan[:max_queries]
        g_ok = 0
        for item in plan:
            try:
                recs = google_news_rss(item["keyword"], item["lang"])
                for r in recs:
                    r.setdefault("track", item["track"])
                    r.setdefault("category", item["category"])
                    r.setdefault("lang", item["lang"])
                records.extend(recs)
                g_ok += 1
            except (urllib.error.URLError, ET.ParseError, ValueError, OSError) as exc:
                errors.append({"stage": "collect", "source": "google", "query": item["keyword"],
                               "lang": item["lang"], "reason": repr(exc)})
        if g_ok:
            source_ok += 1
        elif plan:
            errors.append({"stage": "collect", "source": "google", "level": "warn",
                           "reason": "구글 뉴스 RSS 전량 실패 — 차단 의심(운영 알림)"})

    # ── (비활성) 네이버 HUB ──
    want_naver = naver_hub_enabled() if use_naver_hub is None else use_naver_hub
    if want_naver:
        source_tried += 1
        if not naver_hub_enabled():
            errors.append({"stage": "collect", "source": "naver_hub",
                           "reason": "NAVER_HUB_KEY_ID/NAVER_HUB_KEY 미설정 — 비활성"})
        else:
            n_ok = 0
            for item in build_plan(keywords, only_tracks, only_categories)[: (max_queries or 20)]:
                if item["lang"] != "ko":
                    continue
                try:
                    recs = naver_hub_search(item["keyword"])
                    for r in recs:
                        r.setdefault("track", item["track"])
                        r.setdefault("category", item["category"])
                    records.extend(recs)
                    n_ok += 1
                except (urllib.error.URLError, ValueError, OSError) as exc:
                    errors.append({"stage": "collect", "source": "naver_hub",
                                   "query": item["keyword"], "reason": repr(exc)})
            if n_ok:
                source_ok += 1

    health = update_feed_health(feed_counts) if (track_health and feed_counts) else {}
    coverage = build_coverage(records, feed_counts, registered, health, freshness,
                              stale_thresholds(rss_cfg_used))
    coverage["source_tried"] = source_tried
    coverage["source_ok"] = source_ok
    return records, errors, coverage


# ── CLI ──────────────────────────────────────────────────────────────────────

def run(
    run_id: str | None = None,
    base_dir: Path | None = None,
    keywords_path: Path | None = None,
    *,
    use_rss: bool = True,
    use_google: bool = True,
    max_queries: int | None = None,
    dry_run: bool = False,
    **_legacy: Any,
) -> dict[str, Any]:
    _load_dotenv(common.ROOT / ".env")
    keywords = common.load_keywords(keywords_path)
    run_id = run_id or common.make_run_id()
    base = base_dir or (common.ROOT / "raw")

    if dry_run:
        cfg = rss.load_sources()
        feeds = rss.enabled_sources(cfg)
        plan = build_plan(keywords)
        if max_queries:
            plan = plan[:max_queries]
        print(f"[s1] dry-run run_id={run_id}")
        print(f"[s1] 1순위 RSS 피드 {len(feeds)}개: {[s['id'] for s in feeds]}")
        print(f"[s1] 2순위 구글 쿼리 {len(plan)}건 · 네이버HUB {'ON' if naver_hub_enabled() else 'OFF(비활성)'}")
        return {"feeds": feeds, "plan": plan, "run_id": run_id}

    records, errors, coverage = collect(
        keywords, use_rss=use_rss, use_google=use_google, max_queries=max_queries,
    )
    out_path = base / run_id / "collected.jsonl"
    n = common.write_jsonl(out_path, records)
    (base / run_id / "collected.errors.json").write_text(json.dumps(errors, ensure_ascii=False, indent=2))
    (base / run_id / "coverage.json").write_text(json.dumps(coverage, ensure_ascii=False, indent=2))
    print(f"[s1] collected {n} raw records → {out_path}")
    print(f"[s1] 소스별 {coverage['by_source']} · 피드 {coverage['feed_counts']}")
    if coverage["dead_feeds"]:
        print(f"[s1] ⚠️ 죽은 피드 의심(0건): {coverage['dead_feeds']}")
    if coverage["stale_feeds"]:
        print(f"[s1] ⚠️ 정체된 피드(최신 기사 경과일): {coverage['stale_feeds']}")
    if coverage["unregistered_outlets"]:
        print(f"[s1] ℹ️ RSS 미등록 매체 후보: {list(coverage['unregistered_outlets'])[:5]}")
    if errors:
        print(f"[s1] {len(errors)} source notes/errors (fail-soft)")
    return {"records": records, "errors": errors, "coverage": coverage,
            "run_id": run_id, "out_path": str(out_path)}


def main() -> None:
    ap = argparse.ArgumentParser(description="s1_collect — RSS 1순위 + 구글 보조")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--base-dir", default=None)
    ap.add_argument("--no-rss", action="store_true", help="언론사 RSS 비활성")
    ap.add_argument("--no-google", action="store_true", help="구글 보조 비활성")
    ap.add_argument("--max-queries", type=int, default=None, help="구글 쿼리 상한(테스트용)")
    ap.add_argument("--dry-run", action="store_true", help="네트워크 없이 계획만 출력")
    args = ap.parse_args()
    run(run_id=args.run_id, base_dir=Path(args.base_dir) if args.base_dir else None,
        use_rss=not args.no_rss, use_google=not args.no_google,
        max_queries=args.max_queries, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
