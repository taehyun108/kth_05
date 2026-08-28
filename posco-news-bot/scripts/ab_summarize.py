#!/usr/bin/env python3
"""P0-5 — Ollama 한국어 요약 품질 A/B 하네스 (Z2 에서 실행).

실기사 20건을 후보 모델 2~3개로 각각 요약하고:
  - validate_kakao(본문) 로 ★포맷 통과율★ 자동 측정
  - 사람이 채점할 항목(사실오류 유무·문장 수·자연스러움)을 표로 출력
결과를 CSV + Markdown 으로 저장해 모델을 고를 근거로 삼는다.

판단 기준(docs/11-decisions.md P0-5): 20건 중 사실 오류 2건 이상이면 해당 모델 탈락.

사용:
  cd posco-news-bot
  # 입력: JSONL, 각 줄 {"id","title","outlet","body"} (실기사 20건)
  python -m scripts.ab_summarize --input z2/articles20.jsonl \
      --models "qwen2.5:7b,gemma2:9b,exaone3.5:7.8b"
  # 결과: results/p0-5/ab-<타임스탬프>.{md,csv}
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import time
from pathlib import Path
from typing import Any

from pipeline.stages import common
from pipeline.stages.kakao_format import posco_entities, validate_body
from pipeline.stages.s4_l1 import OllamaClient, build_prompt

_SENT = re.compile(r"(습니다|입니다|합니다|됩니다|니다|다)\.")


def sentence_count(text: str) -> int:
    return len(_SENT.findall(text or ""))


def summarize_one(client: OllamaClient, article: dict[str, Any]) -> dict[str, Any]:
    """모델 1개로 기사 1건 요약 + 자동 지표. 실패해도 예외 없이 행을 남긴다."""
    try:
        raw = client.generate(build_prompt(article))
        obj = json.loads(raw)
        summary = (obj.get("kakao_summary") or "").strip()
        err = None
    except Exception as exc:  # 호출·파싱 실패 → 행에 사유 기록
        summary, err = "", repr(exc)

    ents = posco_entities()
    fmt_errs = validate_body(summary, ents) if summary else ["생성 실패"]
    return {
        "id": article.get("id", ""),
        "summary": summary,
        "char_len": len(summary),
        "sent_count": sentence_count(summary),
        "format_pass": not fmt_errs and err is None,
        "format_errs": "; ".join(fmt_errs),
        "gen_error": err or "",
    }


def run_model(model: str, articles: list[dict[str, Any]], endpoint: str | None) -> dict[str, Any]:
    client = OllamaClient(endpoint=endpoint, model=model)
    available = client.available()
    rows: list[dict[str, Any]] = []
    t0 = time.time()
    if available:
        for a in articles:
            rows.append(summarize_one(client, a))
    elapsed = time.time() - t0
    passed = sum(1 for r in rows if r["format_pass"])
    return {
        "model": model,
        "available": available,
        "count": len(rows),
        "format_pass": passed,
        "pass_rate": round(passed / len(rows), 3) if rows else 0.0,
        "avg_len": round(sum(r["char_len"] for r in rows) / len(rows), 1) if rows else 0,
        "avg_sents": round(sum(r["sent_count"] for r in rows) / len(rows), 1) if rows else 0,
        "elapsed_sec": round(elapsed, 1),
        "rows": rows,
    }


def write_reports(results: list[dict[str, Any]], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = common.now_kst().strftime("%Y%m%d-%H%M")
    md_path = out_dir / f"ab-{ts}.md"
    csv_path = out_dir / f"ab-{ts}.csv"

    lines = ["# P0-5 요약 품질 A/B", "", f"생성: {common.now_kst().isoformat()}", "",
             "## 모델별 집계 (자동)", "",
             "| 모델 | 가용 | 건수 | 포맷통과 | 통과율 | 평균길이 | 평균문장 | 소요(초) |",
             "|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['model']} | {'✅' if r['available'] else '❌'} | {r['count']} | "
                     f"{r['format_pass']} | {r['pass_rate']} | {r['avg_len']} | {r['avg_sents']} | {r['elapsed_sec']} |")
    lines += ["", "## 상세 — ★사람 채점란★ (사실오류: 원문에 없는 내용 Y/N · 자연스러움 1~5)", "",
              "| 모델 | 기사id | 포맷 | 길이 | 문장 | 사실오류(Y/N) | 자연스러움(1-5) | 요약 |",
              "|---|---|---|---|---|---|---|---|"]
    for r in results:
        for row in r["rows"]:
            summ = row["summary"].replace("|", "\\|") or f"(실패: {row['gen_error'] or row['format_errs']})"
            fmt = "PASS" if row["format_pass"] else "FAIL"
            lines.append(f"| {r['model']} | {row['id']} | {fmt} | {row['char_len']} | "
                         f"{row['sent_count']} |  |  | {summ} |")
    lines += ["", "## 판정 가이드", "",
              "- 포맷 통과율이 낮으면 프롬프트/모델 부적합.",
              "- **사실오류 2건 이상이면 해당 모델 탈락** (docs/11-decisions.md P0-5).",
              "- 통과 모델 중 자연스러움 평균이 가장 높은 모델을 채택. 미달 시 L0 추출 요약 유지.", ""]
    md_path.write_text("\n".join(lines), encoding="utf-8")

    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["model", "id", "format_pass", "char_len", "sent_count",
                    "hallucination_YN", "naturalness_1to5", "format_errs", "summary"])
        for r in results:
            for row in r["rows"]:
                w.writerow([r["model"], row["id"], row["format_pass"], row["char_len"],
                            row["sent_count"], "", "", row["format_errs"], row["summary"]])
    return md_path, csv_path


def main() -> None:
    ap = argparse.ArgumentParser(description="P0-5 Ollama 요약 품질 A/B")
    ap.add_argument("--input", required=True, help="JSONL: {id,title,outlet,body} 실기사 20건")
    ap.add_argument("--models", required=True, help="쉼표구분 모델명 (예: qwen2.5:7b,gemma2:9b)")
    ap.add_argument("--endpoint", default=None, help="OLLAMA_ENDPOINT 오버라이드")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    articles = list(common.read_jsonl(Path(args.input)))
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    out_dir = Path(args.out_dir) if args.out_dir else (common.ROOT / "results" / "p0-5")

    print(f"[ab] 입력 {len(articles)}건 · 모델 {models}")
    results = [run_model(m, articles, args.endpoint) for m in models]
    for r in results:
        note = "" if r["available"] else " (Ollama 미응답 — 건너뜀)"
        print(f"[ab] {r['model']}: 통과율 {r['pass_rate']} · 평균 {r['avg_len']}자 "
              f"{r['avg_sents']}문장 · {r['elapsed_sec']}초{note}")
    md, csvp = write_reports(results, out_dir)
    print(f"[ab] 저장: {md}\n[ab] 저장: {csvp}")
    print("[ab] 다음: md 파일의 사람 채점란(사실오류·자연스러움)을 채워 모델을 고르세요.")


if __name__ == "__main__":
    main()
