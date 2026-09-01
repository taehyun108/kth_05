"""공통 유틸 — 키워드 로드 · canonical URL · 기사 id · JSONL IO · 시각.

INV-1: 트랙별 분기 없는 공통 처리. 여기의 함수는 전 트랙이 동일하게 쓴다.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml

# 저장소 루트 (pipeline/stages/common.py → parents[2] = posco-news-bot/)
ROOT = Path(__file__).resolve().parents[2]
KEYWORDS_PATH = ROOT / "pipeline" / "keywords.yaml"

KST = timezone(timedelta(hours=9))

# canonical URL 에서 제거하는 트래킹 파라미터 (docs/01-collect.md §4.2.1)
TRACKING_PARAM_PREFIXES = ("utm_",)
TRACKING_PARAM_KEYS = {
    "sid", "ref", "fbclid", "gclid", "igshid", "spm", "cmpid",
    "ncid", "mc_cid", "mc_eid", "_hsenc", "_hsmi", "oc", "ocid",
}


def load_keywords(path: Path | str | None = None) -> dict[str, Any]:
    """keywords.yaml 로드."""
    p = Path(path) if path else KEYWORDS_PATH
    with p.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def track_langs(keywords: dict[str, Any], track: str, category_cfg: dict[str, Any] | None = None) -> list[str]:
    """카테고리 lang 우선, 없으면 track_lang 기본값, 그래도 없으면 ['ko'].

    T1 posco / T2 battery → ['ko'] · T3 policy / T4 trade → ['ko','en']
    """
    if category_cfg and category_cfg.get("lang"):
        return list(category_cfg["lang"])
    return list(keywords.get("track_lang", {}).get(track, ["ko"]))


def canonical_url(url: str) -> str:
    """정본 URL — 트래킹 파라미터·프래그먼트 제거, 호스트 소문자화, 기본포트 제거.

    같은 기사가 네이버·구글 양쪽에서 잡혀도 동일 canonical 로 수렴시키는 것이 목적.
    """
    url = (url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    scheme = (parts.scheme or "http").lower()
    host = (parts.hostname or "").lower()
    # 기본 포트 제거
    port = parts.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    else:
        netloc = host
    # 쿼리에서 트래킹 파라미터 제거 후 정렬 (순서 흔들림에도 동일 결과)
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not (k.lower().startswith(TRACKING_PARAM_PREFIXES) or k.lower() in TRACKING_PARAM_KEYS)
    ]
    query = urlencode(sorted(kept))
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, query, ""))  # fragment 제거


def sha1_hex(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def make_article_id(canonical: str, date: str) -> str:
    """기사 id = 날짜 + '-' + sha1(canonical_url)[:10]  (docs §4.2.1)."""
    return f"{date}-{sha1_hex(canonical)[:10]}"


def to_kst_date(dt_iso: str | None, fallback: datetime | None = None) -> str:
    """발행 시각(ISO) → KST 날짜 YYYY-MM-DD. 파싱 실패 시 fallback(now) 날짜."""
    if dt_iso:
        try:
            s = dt_iso.strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=KST)
            return dt.astimezone(KST).date().isoformat()
        except (ValueError, TypeError):
            pass
    base = fallback or datetime.now(KST)
    return base.astimezone(KST).date().isoformat()


def parse_dt(dt_iso: str | None) -> datetime | None:
    if not dt_iso:
        return None
    try:
        s = dt_iso.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        return dt.astimezone(KST)
    except (ValueError, TypeError):
        return None


def now_kst() -> datetime:
    return datetime.now(KST)


def state_dir() -> Path:
    """상태 파일 위치. PNB_STATE_DIR 로 재정의 가능(테스트는 tmp 로 격리)."""
    import os
    d = os.environ.get("PNB_STATE_DIR")
    return Path(d) if d else ROOT / "pipeline" / "state"


def make_run_id(now: datetime | None = None) -> str:
    now = now or now_kst()
    return now.astimezone(KST).strftime("%Y%m%d-%H%M")


# ── JSONL IO (스테이지 간 통신은 파일로만) ───────────────────────────────

def write_jsonl(path: Path | str, rows: Iterable[dict[str, Any]]) -> int:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with p.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def read_jsonl(path: Path | str) -> Iterator[dict[str, Any]]:
    p = Path(path)
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def input_hash(rows: list[dict[str, Any]]) -> str:
    """입력 멱등성 해시 — 출력 존재 + 동일 해시면 스킵 (CLAUDE.md 코딩 규칙)."""
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True)
    return sha1_hex(payload)


_WS = re.compile(r"\s+")


def collapse_ws(text: str) -> str:
    return _WS.sub(" ", (text or "")).strip()
