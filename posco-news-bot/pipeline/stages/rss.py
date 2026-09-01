"""rss — 언론사 RSS 피드 수집 + ★정규화 계층★ (docs/01-collect.md §F-01).

검색 API 와 다른 점: 질의가 아니라 피드 전체를 받아온다. 매체마다 포맷 편차가 커서
이 모듈이 그 차이를 흡수하고 하류에는 항상 같은 모양의 레코드를 넘긴다.

흡수하는 편차:
  - 포맷      RSS 2.0(<item>) / Atom(<entry>)
  - 날짜      RFC822(+0900 · GMT) · ISO8601(Z · 오프셋) · 공백구분 naive
  - 설명      description 없음 → content:encoded → summary → 빈 문자열
  - 제목·본문 CDATA · HTML 태그 · HTML 엔티티
  - 링크      <link>텍스트 / Atom <link href=...>
  - 카테고리  <category> 다중 · Atom <category term=...>
원문 URL 이 그대로 오므로 네이버 중계링크(originallink) 처리 로직은 필요 없다.
"""
from __future__ import annotations

import html as _html
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import yaml

from . import common

USER_AGENT = "posco-news-bot/0.1 (+https://github.com/taehyun108/kth_05)"
_TAG = re.compile(r"<[^>]+>")

# 네임스페이스 (dc:date, content:encoded, atom)
NS = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "atom": "http://www.w3.org/2005/Atom",
}


def clean_text(text: str | None) -> str:
    """CDATA·HTML 태그·엔티티 제거 후 공백 정리. (ET 가 CDATA 는 이미 평문으로 준다)"""
    return common.collapse_ws(_html.unescape(_TAG.sub(" ", text or "")))


# ── 날짜 정규화 (매체별 편차의 최대 원인) ───────────────────────────────────

_NAIVE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S")


def parse_date_any(raw: str | None) -> str | None:
    """어떤 포맷이 오든 KST ISO8601 로. 실패 시 None (하류가 수집시각으로 폴백)."""
    s = (raw or "").strip()
    if not s:
        return None
    # 1) RFC822 — "Mon, 01 Sep 2026 09:00:00 +0900" / "... GMT"
    try:
        dt = parsedate_to_datetime(s)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=common.KST)
            return dt.astimezone(common.KST).isoformat()
    except (TypeError, ValueError, IndexError):
        pass
    # 2) ISO8601 — "2026-09-01T09:00:00+09:00" / "...Z"
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=common.KST)
        return dt.astimezone(common.KST).isoformat()
    except ValueError:
        pass
    # 3) naive 문자열
    for fmt in _NAIVE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=common.KST)
            return dt.astimezone(common.KST).isoformat()
        except ValueError:
            continue
    return None


# ── 항목 파싱 ────────────────────────────────────────────────────────────────

def _first_text(el: ET.Element, paths: list[str]) -> str | None:
    for p in paths:
        found = el.find(p, NS) if (":" in p or p.startswith(".")) else el.find(p)
        if found is not None and (found.text or "").strip():
            return found.text
    return None


def _link_of(el: ET.Element) -> str:
    # RSS: <link>URL</link> · Atom: <link href="URL"/>
    link = el.find("link")
    if link is not None:
        if (link.text or "").strip():
            return link.text.strip()
        href = link.get("href")
        if href:
            return href.strip()
    a = el.find("atom:link", NS)
    if a is not None and a.get("href"):
        return a.get("href").strip()
    return ""


def _categories(el: ET.Element) -> list[str]:
    out: list[str] = []
    for c in el.findall("category") + el.findall("atom:category", NS):
        val = (c.text or "").strip() or (c.get("term") or "").strip()
        if val:
            out.append(clean_text(val))
    return out


def parse_items(xml_bytes: bytes, source: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """피드 XML → 정규화 레코드 목록. RSS 2.0 / Atom 모두 처리."""
    src = source or {}
    root = ET.fromstring(xml_bytes)
    nodes = root.iterfind(".//item")
    items = list(nodes)
    if not items:                                  # Atom 폴백
        items = list(root.iterfind(".//atom:entry", NS)) or list(root.iterfind(".//entry"))

    out: list[dict[str, Any]] = []
    for el in items:
        title = clean_text(_first_text(el, ["title", "atom:title"]))
        if not title:
            continue                               # 제목 없는 항목은 버린다
        desc_raw = _first_text(el, ["description", "content:encoded", "summary",
                                    "atom:summary", "atom:content"])
        published = parse_date_any(_first_text(
            el, ["pubDate", "dc:date", "updated", "atom:updated", "published", "atom:published"]))
        out.append({
            "title": title,
            "url": _link_of(el),
            "description": clean_text(desc_raw),   # 없으면 "" (하류가 degrade)
            "published_at": published,             # 없으면 None
            "categories": _categories(el),
            "outlet": src.get("name"),
            "lang": src.get("lang") or "ko",
            "source": "rss",
            "source_id": src.get("id"),
            "source_type": src.get("source_type", "news"),
        })
        if src.get("max_items") and len(out) >= int(src["max_items"]):
            break
    return out


# ── 소스 정의 로드 · 수집 ────────────────────────────────────────────────────

def load_sources(path: Path | str | None = None) -> dict[str, Any]:
    p = Path(path) if path else (common.ROOT / "pipeline" / "rss_sources.yaml")
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    defaults = cfg.get("defaults") or {}
    merged = []
    for s in cfg.get("sources") or []:
        merged.append({**defaults, **s})
    cfg["sources"] = merged
    return cfg


def enabled_sources(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in cfg.get("sources", []) if s.get("enabled")]


def fetch_bytes(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_source(src: dict[str, Any], fetcher=None) -> list[dict[str, Any]]:
    """피드 1건 수집. fetcher 주입 가능(테스트는 합성 XML)."""
    get = fetcher or (lambda u: fetch_bytes(u, int(src.get("timeout_sec", 15))))
    return parse_items(get(src["url"]), src)


def collect_feeds(cfg: dict[str, Any], fetcher=None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """활성 피드를 모두 수집. 개별 실패는 fail-soft, 전부 실패면 호출측이 판단.

    반환: (records, errors, per_feed_counts)
    """
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for src in enabled_sources(cfg):
        fid = src.get("id", src.get("url", "?"))
        try:
            items = fetch_source(src, fetcher)
            records.extend(items)
            counts[fid] = len(items)
        except (urllib.error.URLError, ET.ParseError, ValueError, OSError) as exc:
            counts[fid] = 0
            errors.append({"stage": "collect", "source": "rss", "feed": fid,
                           "verified": bool(src.get("verified")), "reason": repr(exc)})
    return records, errors, counts
