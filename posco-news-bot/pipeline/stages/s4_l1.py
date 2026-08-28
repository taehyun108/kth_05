"""s4_l1 — L1 생성 요약 (Ollama 로컬 LLM). 카톡 발송의 실입력을 만든다.

L0 추출 요약은 반말 평서문이라 카톡 고정 포맷을 못 맞춘다(INV-10).
L1 이 존댓말 `kakao_summary` + `tone` 을 생성하고, kakao_format 으로 자체 검증한다.

원칙:
  - 모델명·엔드포인트는 env 로 교체 (OLLAMA_ENDPOINT, OLLAMA_MODEL)
  - 생성 결과를 validate_body 로 검증 → 실패 시 재시도 1회 → 그래도 실패면 L0 유지
  - Ollama 미설치/미응답이면 전체 스킵하고 L0 유지 (INV-6 — L0만으로 발행·발송 가능)
  - 입력 id echo 강제 (배치 순서 뒤바뀜 방지 — 여기선 건별 호출이라 자연히 보장)
"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Protocol

from . import common
from .kakao_format import posco_entities, validate_body

TONES = {"positive", "neutral", "negative", "crisis"}


# ── LLM 클라이언트 (주입식 — 테스트는 모의 클라이언트) ──────────────────────

class LLMClient(Protocol):
    def available(self) -> bool: ...
    def generate(self, prompt: str) -> str: ...


class OllamaClient:
    """Ollama /api/generate 호출. 모델·엔드포인트는 env 로 교체 가능."""

    def __init__(self, endpoint: str | None = None, model: str | None = None, timeout: int = 120) -> None:
        self.endpoint = (endpoint or __import__("os").environ.get("OLLAMA_ENDPOINT")
                         or "http://localhost:11434").rstrip("/")
        self.model = model or __import__("os").environ.get("OLLAMA_MODEL") or "qwen2.5:7b"
        self.timeout = timeout

    def available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.endpoint}/api/tags")
            with urllib.request.urlopen(req, timeout=5):
                return True
        except (urllib.error.URLError, OSError):
            return False

    def generate(self, prompt: str) -> str:
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",          # JSON 강제
            "options": {"temperature": 0.2},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.endpoint}/api/generate", data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read())
        return data.get("response", "")


# ── 프롬프트 ────────────────────────────────────────────────────────────────

PROMPT_TEMPLATE = """당신은 포스코 대외협력팀의 뉴스 요약 담당입니다.
아래 기사를 카카오톡 단체방용으로 요약하세요. 규칙을 반드시 지키십시오.

[규칙]
- 존댓말 평서문으로만 작성합니다. 모든 문장은 "습니다." 또는 "입니다." 등으로 끝냅니다.
- 첫머리는 반드시 "[{outlet}] " 로 시작합니다(대괄호 안은 매체명, 뒤 공백 1칸).
- 한 문단으로 이어 씁니다. 줄바꿈·이모지·불릿·해시태그·URL 을 넣지 않습니다.
- 3~5문장, 전체 150~350자.
- 포스코 계열사(포스코퓨처엠 등)가 등장하는 문장을 반드시 포함합니다.
- 원문 문장을 그대로 옮기지 말고 자체 문장으로 재작성합니다.
- SWOT·시사점·대응논리는 넣지 않습니다.

[기사]
제목: {title}
매체: {outlet}
본문: {body}

[출력] 아래 JSON 만 출력하세요. 다른 텍스트 금지.
{{"id": "{id}", "kakao_summary": "<요약>", "tone": "<positive|neutral|negative|crisis>"}}
"""


def build_prompt(article: dict[str, Any]) -> str:
    body = article.get("_body") or article.get("summary") or article.get("description") or ""
    return PROMPT_TEMPLATE.format(
        id=article.get("id", ""),
        outlet=article.get("outlet") or "언론",
        title=article.get("title", ""),
        body=body[:1200],  # 본문 앞 1200자로 절삭 (docs §11.6.4)
    )


def _parse(resp: str, article_id: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(resp)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    # 입력 id echo 검증 (있으면 대조)
    if obj.get("id") and obj.get("id") != article_id:
        return None
    return obj


# ── 건별 생성 (검증 → 재시도 → L0 유지) ─────────────────────────────────────

def enrich_one(
    article: dict[str, Any],
    client: LLMClient,
    entities: list[str] | None = None,
    max_attempts: int = 2,
) -> tuple[dict[str, Any], str]:
    """생성 요약을 붙인다. 반환: (article, status).

    status: 'ok' | 'l1_failed'(검증 미달 → L0 유지) | 'error'(호출 실패 → L0 유지)
    """
    ents = entities if entities is not None else posco_entities()
    aid = article.get("id", "")
    last_errs: list[str] = []
    for _ in range(max_attempts):
        try:
            resp = client.generate(build_prompt(article))
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            article["l1_error"] = repr(exc)
            return article, "error"  # 호출 실패 → L0 유지 (INV-6)
        obj = _parse(resp, aid)
        if not obj:
            last_errs = ["JSON 파싱 실패"]
            continue
        summary = (obj.get("kakao_summary") or "").strip()
        tone = obj.get("tone") if obj.get("tone") in TONES else None
        errs = validate_body(summary, ents)
        if not errs:
            article["kakao_summary"] = summary
            article["tone"] = tone or article.get("tone")
            article["summary_method"] = "generative"  # ★카톡 발송 게이트 통과 자격★
            article["analysis_level"] = "L1"
            return article, "ok"
        last_errs = errs
    # 검증 미달 — 억지로 쓰지 않고 L0 유지 (summary_method 는 extractive 그대로)
    article["l1_reject"] = last_errs
    return article, "l1_failed"


# ── 배치 실행 ────────────────────────────────────────────────────────────────

def should_enrich(article: dict[str, Any]) -> bool:
    # 카톡 후보(posco_relevance != none)만 L1 생성 요약 대상 — 소량·고가치
    return article.get("posco_relevance") in ("primary", "mention")


def enrich(
    articles: list[dict[str, Any]],
    client: LLMClient,
    entities: list[str] | None = None,
) -> dict[str, Any]:
    ents = entities if entities is not None else posco_entities()
    stats = {"ok": 0, "l1_failed": 0, "error": 0, "skipped": 0, "not_target": 0}
    out: list[dict[str, Any]] = []

    if not client.available():
        # Ollama 미설치/미응답 → 전체 L0 유지 (INV-6)
        for a in articles:
            out.append(a)
            stats["skipped"] += 1
        return {"articles": out, "stats": stats, "available": False}

    for a in articles:
        if not should_enrich(a):
            out.append(a)
            stats["not_target"] += 1
            continue
        enriched, status = enrich_one(a, client, ents)
        out.append(enriched)
        stats[status] = stats.get(status, 0) + 1
    return {"articles": out, "stats": stats, "available": True}


def run(run_id: str, base_dir: Path | None = None, keywords_path: Path | None = None) -> dict[str, Any]:
    base = base_dir or (common.ROOT / "raw")
    in_path = base / run_id / "analyzed.jsonl"
    out_path = base / run_id / "l1.jsonl"
    records = list(common.read_jsonl(in_path))

    ih = common.input_hash(records)
    meta_path = base / run_id / "l1.meta"
    if out_path.exists() and meta_path.exists() and meta_path.read_text().strip() == ih:
        print(f"[s4_l1] skip (idempotent) run_id={run_id}")
        return {"skipped": True}

    ents = None
    if keywords_path:
        import yaml
        ents = [a for al in (yaml.safe_load(Path(keywords_path).read_text(encoding="utf-8"))
                             .get("posco_entities") or {}).values() for a in al]
    result = enrich(records, OllamaClient(), ents)
    common.write_jsonl(out_path, result["articles"])
    meta_path.write_text(ih)
    (base / run_id / "l1.summary.json").write_text(
        json.dumps({"stats": result["stats"], "available": result["available"]},
                   ensure_ascii=False, indent=2)
    )
    if not result["available"]:
        print("[s4_l1] Ollama 미응답 — 전체 L0 유지 (INV-6). 카톡은 extractive 스킵됨.")
    print(f"[s4_l1] stats: {result['stats']}")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="s4_l1 — Ollama 생성 요약(카톡 입력)")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--base-dir", default=None)
    args = ap.parse_args()
    run(args.run_id, base_dir=Path(args.base_dir) if args.base_dir else None)


if __name__ == "__main__":
    main()
