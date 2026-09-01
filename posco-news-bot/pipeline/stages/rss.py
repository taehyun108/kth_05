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
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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
    """소스 정의 로드.

    ★verified 가 아닌 피드는 강제로 비활성★ — 예외 없음.
    주소를 추정으로 적어 둔 피드가 켜져 있으면, 그 추정이 틀렸을 때
    '수집이 도는 것처럼 보이는데 실제로는 비어 있는' 상태가 된다.
    실제로 전자신문 섹션 번호 추정이 틀렸고(속보를 배터리로 오인),
    이데일리 /rss/ 는 200 을 주면서 오류 페이지였다. 확인된 것만 켠다.
    """
    p = Path(path) if path else (common.ROOT / "pipeline" / "rss_sources.yaml")
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    defaults = cfg.get("defaults") or {}
    merged = []
    for s in cfg.get("sources") or []:
        src = {**defaults, **s}
        if src.get("enabled") and not src.get("verified"):
            src["enabled"] = False
            src["disabled_reason"] = "unverified"      # 리포트에서 구분하려고 남긴다
        merged.append(src)
    cfg["sources"] = merged
    return cfg


def enabled_sources(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in cfg.get("sources", []) if s.get("enabled")]


def unverified_sources(cfg: dict[str, Any]) -> list[str]:
    """미확인이라 돌지 않는 피드 id — S8 리포트에 '확인 대기'로 노출한다.

    enabled 를 어떻게 적었든 verified 가 아니면 돌지 않으므로 함께 묶는다.
    이게 안 보이면 '등록은 해뒀는데 아무도 확인 안 한' 피드가 조용히 쌓인다.
    """
    return [s.get("id", "?") for s in cfg.get("sources", []) if not s.get("verified")]


# ── 응답 검증 (★200 은 성공을 뜻하지 않는다★) ───────────────────────────────

@dataclass
class FeedResponse:
    body: bytes
    content_type: str = ""
    final_url: str = ""
    status: int = 200


# 오류 페이지로 넘길 때 URL 에 흔히 붙는 표식
_ERROR_URL_MARKERS = ("aspxerrorpath", "errorpath", "/error", "404", "notfound", "not_found")
_XMLISH = ("xml", "rss", "atom")


class FeedInvalid(ValueError):
    """200 을 받았지만 피드가 아니다. reason 이 리포트에 그대로 실린다."""


def _same_resource(requested: str, final: str) -> bool:
    """리다이렉트가 '같은 자원'인지. 호스트/경로가 바뀌면 다른 자원으로 본다."""
    if not final:
        return True
    a, b = urlsplit(requested), urlsplit(final)
    ha = (a.hostname or "").lower().removeprefix("www.")
    hb = (b.hostname or "").lower().removeprefix("www.")
    if ha != hb:
        return False
    return a.path.rstrip("/") == b.path.rstrip("/")


def validate_response(src: dict[str, Any], resp: FeedResponse) -> None:
    """파싱 전에 거른다. 실패 사유는 사람이 읽고 조치할 수 있는 문장으로.

    검사 순서는 '무엇이 잘못됐는지 가장 잘 설명하는 것' 우선이다.
    """
    url = src.get("url", "")
    final = resp.final_url or url

    # ① 오류 페이지로 리다이렉트 — 이데일리 /rss/ 사례
    low_final = final.lower()
    if any(m in low_final for m in _ERROR_URL_MARKERS):
        raise FeedInvalid(f"오류 페이지로 리다이렉트 ({final})")
    if not _same_resource(url, final):
        raise FeedInvalid(f"다른 주소로 리다이렉트 ({url} → {final})")

    # ② Content-Type 이 xml 계열이 아님
    ctype = (resp.content_type or "").split(";")[0].strip().lower()
    if ctype and not any(x in ctype for x in _XMLISH):
        raise FeedInvalid(f"200 이지만 XML 아님 (Content-Type: {ctype})")

    # ③ 루트 엘리먼트
    try:
        root = ET.fromstring(resp.body)
    except ET.ParseError as exc:
        raise FeedInvalid(f"200 이지만 XML 파싱 실패 ({exc})") from exc
    tag = root.tag.rsplit("}", 1)[-1].lower()
    if tag not in ("rss", "feed", "rdf"):
        raise FeedInvalid(f"200 이지만 피드 아님 (루트 <{tag}>)")

    # ④ 항목이 최소 1건
    n = len(list(root.iterfind(".//item"))) or len(list(root.iterfind(".//atom:entry", NS))) \
        or len(list(root.iterfind(".//entry")))
    if n == 0:
        raise FeedInvalid("피드 구조는 맞지만 item/entry 0건")


def fetch_response(url: str, timeout: int = 15) -> FeedResponse:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return FeedResponse(
            body=resp.read(),
            content_type=resp.headers.get("Content-Type", ""),
            final_url=resp.geturl(),           # 리다이렉트 후 최종 URL
            status=getattr(resp, "status", 200),
        )


def fetch_bytes(url: str, timeout: int = 15) -> bytes:
    """(구 인터페이스) 본문만 필요할 때."""
    return fetch_response(url, timeout).body


def _as_response(raw: Any, url: str) -> FeedResponse:
    """fetcher 가 bytes 를 주든 FeedResponse 를 주든 하나로 맞춘다(테스트 편의)."""
    if isinstance(raw, FeedResponse):
        return raw
    return FeedResponse(body=raw, content_type="application/xml", final_url=url)


def fetch_source(src: dict[str, Any], fetcher=None) -> list[dict[str, Any]]:
    """피드 1건 수집 — ★검증 후★ 파싱. fetcher 주입 가능(테스트는 합성 XML)."""
    get = fetcher or (lambda u: fetch_response(u, int(src.get("timeout_sec", 15))))
    resp = _as_response(get(src["url"]), src["url"])
    validate_response(src, resp)
    return parse_items(resp.body, src)


# ── 카테고리 필터 (피드가 <category> 를 주는 경우) ──────────────────────────

def category_allows(src: dict[str, Any], item: dict[str, Any]) -> bool:
    """피드별 category_filter — 없으면 전부 통과.

    이데일리처럼 전 분야 firehose 인데 <category> 가 채워져 오는 피드용.
    카테고리로 1차로 줄이고, 그 다음 keywords.yaml 로 2차로 거른다.
    카테고리가 비어 있는 항목은 ★버리지 않는다★ — 분류 누락으로 기사를 잃지 않으려고.
    """
    wanted = src.get("category_filter")
    if not wanted:
        return True
    cats = item.get("categories") or []
    if not cats:
        return True
    low = [c.lower() for c in cats]
    return any(w.lower() in c for w in wanted for c in low)


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
            kept = [i for i in items if category_allows(src, i)]
            records.extend(kept)
            counts[fid] = len(kept)
            if len(kept) != len(items):
                errors.append({"stage": "collect", "source": "rss", "feed": fid, "level": "info",
                               "reason": f"category_filter: {len(items)} → {len(kept)}건"})
        except FeedInvalid as exc:
            # ★200 이어도 피드가 아니면 수집 실패다★ — 사유를 그대로 리포트에 싣는다
            counts[fid] = 0
            errors.append({"stage": "collect", "source": "rss", "feed": fid, "level": "error",
                           "kind": "invalid_response", "url": src.get("url"),
                           "verified": bool(src.get("verified")), "reason": str(exc)})
        except (urllib.error.URLError, ET.ParseError, ValueError, OSError) as exc:
            counts[fid] = 0
            errors.append({"stage": "collect", "source": "rss", "feed": fid, "level": "error",
                           "kind": "fetch_error", "url": src.get("url"),
                           "verified": bool(src.get("verified")), "reason": repr(exc)})
    return records, errors, counts
