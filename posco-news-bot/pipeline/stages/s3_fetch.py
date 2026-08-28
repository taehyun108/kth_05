"""s3_fetch — 본문 크롤링 (자리표시자).

⚠️ 실제 크롤러(trafilatura→readability→newspaper3k, robots, 도메인 큐)는
   Z2 실데이터 스모크 결과 확인 후 구현한다(docs/01-collect.md §F-03, INV-5).
   지금은 네트워크 없이 스킵한다 — 하류(s4_analyze)는 본문이 없으면
   description 스니펫으로 degrade 하므로 L0 발행이 그대로 성립한다(INV-6).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import common


def run(run_id: str, base_dir: Path | None = None) -> dict[str, Any]:
    """placeholder — 크롤링 없이 스킵. normalized.jsonl 을 그대로 통과시킨다."""
    base = base_dir or (common.ROOT / "raw")
    norm = base / run_id / "normalized.jsonl"
    n = sum(1 for _ in common.read_jsonl(norm)) if norm.exists() else 0
    print(f"[s3] fetch 미구현 — 스킵 (normalized {n}건, 본문은 캐시 없음 → 스니펫 degrade)")
    return {"skipped": True, "reason": "not_implemented", "input_count": n}
