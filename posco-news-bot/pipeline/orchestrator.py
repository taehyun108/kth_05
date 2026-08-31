"""orchestrator — 파이프라인 DAG 실행 (docs/09-orchestrator.md).

설계 목표: 재개 가능 · 멱등 · 부분실패 허용(fail-soft) · 발송 fail-closed · 관측 가능 · 드라이런.
스테이지는 입력파일→출력파일로만 통신하고, 상태는 state/run-<run_id>.json 에 체크포인트한다.

사용:
  python pipeline/orchestrator.py --mode daily
  python pipeline/orchestrator.py --mode daily --dry-run
  python pipeline/orchestrator.py --resume <run_id> [--only S4,S6,S7]
  python pipeline/orchestrator.py --mode backfill --since ... --until ...   # 발송 강제 차단
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

# 스크립트로도(`python pipeline/orchestrator.py`), 모듈로도(`-m`) 실행 가능하게
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.stages import (
    common, s1_collect, s2_normalize, s3_fetch, s4_analyze, s4_l1, s5_swot, s6_publish, s7_dispatch,
    s7_mail, stagers,
)

# 실패 정책 (docs §11.5)
FAIL_HARD = "fail-hard"      # 실패 시 즉시 중단
FAIL_SOFT = "fail-soft"      # 실패해도 계속
FAIL_CLOSED = "fail-closed"  # 발송 — 판정 불가 시 보내지 않음(계속)

Status = Literal["success", "partial", "failed", "skipped"]
Mode = Literal["daily", "intraday", "dryrun", "backfill"]


@dataclass
class StageResult:
    stage: str
    status: Status
    input_count: int = 0
    output_count: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    duration_sec: float = 0.0
    cost: dict[str, Any] = field(default_factory=lambda: {"api_calls": 0, "usd": 0.0})
    checkpoint: str = ""
    note: str = ""


@dataclass
class StageContext:
    run_id: str
    base_dir: Path
    data_dir: Path
    mode: Mode
    dispatch_allowed: bool
    params: dict[str, Any]
    state: dict[str, Any]
    extras: dict[str, Any] = field(default_factory=dict)  # 주입(어댑터·클라이언트·라우트)


@dataclass
class Stage:
    name: str
    fn: Callable[[StageContext], StageResult]
    policy: str


# ── 스테이지 어댑터 (기존 run() → StageResult) ──────────────────────────────

def _s0_preflight(ctx: StageContext) -> StageResult:
    # 키·쿼터 대신(키 없음) 디스크·스키마 최소 검증
    common.load_keywords()  # keywords.yaml 파싱 실패 시 예외 → failed
    (ctx.base_dir / ctx.run_id).mkdir(parents=True, exist_ok=True)
    return StageResult("S0", "success", note="preflight ok")


def _s1_collect(ctx: StageContext) -> StageResult:
    res = s1_collect.run(
        run_id=ctx.run_id, base_dir=ctx.base_dir,
        use_naver=ctx.params.get("use_naver", True),
        max_queries=ctx.params.get("max_queries"),
    )
    recs = res.get("records", [])
    errs = res.get("errors", [])
    # 0건이어도(네트워크 없음) 중단하지 않는다 — partial 로 계속(하류가 빈 입력 처리)
    status: Status = "partial" if errs or not recs else "success"
    return StageResult("S1", status, output_count=len(recs), errors=errs,
                       artifacts=[str(ctx.base_dir / ctx.run_id / "collected.jsonl")])


def _s2_normalize(ctx: StageContext) -> StageResult:
    res = s2_normalize.run(ctx.run_id, base_dir=ctx.base_dir)
    if res.get("skipped"):
        return StageResult("S2", "skipped", note="idempotent")
    c = res["meta"]["counts"]
    return StageResult("S2", "success", input_count=c["collected"], output_count=c["kept"],
                       errors=res.get("errors", []))


def _s3_fetch(ctx: StageContext) -> StageResult:
    res = s3_fetch.run(ctx.run_id, base_dir=ctx.base_dir)
    return StageResult("S3", "skipped", input_count=res.get("input_count", 0),
                       note=res.get("reason", "not_implemented"))


def _s4_analyze(ctx: StageContext) -> StageResult:
    res = s4_analyze.run(ctx.run_id, base_dir=ctx.base_dir)
    if res.get("skipped"):
        return StageResult("S4", "skipped", note="idempotent")
    return StageResult("S4", "success", output_count=res["meta"]["count"],
                       errors=res.get("errors", []))


def _s4_l1(ctx: StageContext) -> StageResult:
    # Ollama 없으면 enrich 가 스킵하고 L0 유지 (INV-6)
    client = ctx.extras.get("llm_client") or s4_l1.OllamaClient()
    records = list(common.read_jsonl(ctx.base_dir / ctx.run_id / "analyzed.jsonl"))
    result = s4_l1.enrich(records, client)
    common.write_jsonl(ctx.base_dir / ctx.run_id / "l1.jsonl", result["articles"])
    if not result["available"]:
        return StageResult("S4L1", "skipped", output_count=len(result["articles"]),
                           note="Ollama 미응답 — L0 유지")
    st = result["stats"]
    status: Status = "partial" if st.get("l1_failed") or st.get("error") else "success"
    return StageResult("S4L1", status, output_count=st.get("ok", 0), cost={"api_calls": st.get("ok", 0)},
                       note=str(st))


def _s5_swot(ctx: StageContext) -> StageResult:
    # 클러스터링은 L0(결정론). SWOT 텍스트 생성은 L2 — 키 없으면 클러스터만 유지(INV-6).
    src = ctx.base_dir / ctx.run_id / "l1.jsonl"
    if not src.exists():
        src = ctx.base_dir / ctx.run_id / "analyzed.jsonl"
    articles = list(common.read_jsonl(src)) if src.exists() else []
    issues_path = ctx.data_dir / "issues.json"
    existing = []
    if issues_path.exists():
        existing = json.loads(issues_path.read_text(encoding="utf-8")).get("issues", [])
    issues = s5_swot.cluster(articles, existing)          # id 안정: 기존 이슈에 기사만 추가
    s5_swot.write_issues(issues, data_dir=ctx.data_dir)
    corr = s5_swot.count_axis_corrections(issues)          # L2 축 교정 건수(프롬프트 튜닝 신호)
    ctx.state["axis_corrections_total"] = corr

    # 정책·통상 엔티티(L0 stager) → full(L2) + board(L1) 발행
    def _load(name: str) -> list:
        p = ctx.data_dir / f"{name}.json"
        return json.loads(p.read_text(encoding="utf-8")).get(name, []) if p.exists() else []

    policies = stagers.build_policies(articles, existing=_load("policies"))
    disputes = stagers.build_disputes(articles, existing=_load("disputes"))
    _write_json(ctx.data_dir / "policies.json", {"policies": policies})
    _write_json(ctx.data_dir / "policy_board.json", {"policies": stagers.policy_board(policies)})
    _write_json(ctx.data_dir / "disputes.json", {"disputes": disputes})
    _write_json(ctx.data_dir / "dispute_board.json", {"disputes": stagers.dispute_board(disputes)})

    return StageResult("S5", "success", output_count=len(issues),
                       artifacts=[str(issues_path)],
                       note=f"이슈 {len(issues)} · 정책 {len(policies)} · 분쟁 {len(disputes)} · 축 교정 {corr}건")


def _write_json(path: Path, body: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": "1.0", "generated_at": common.now_kst().isoformat(), **body}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _s6_publish(ctx: StageContext) -> StageResult:
    res = s6_publish.run(ctx.run_id, base_dir=ctx.base_dir, data_dir=ctx.data_dir)
    return StageResult("S6", "success", output_count=res["output_count"],
                       artifacts=[res["path"]], note=str(res["counts"]))


def _s7_dispatch(ctx: StageContext) -> StageResult:
    already = set(ctx.state.get("dispatch_log", []))
    res = s7_dispatch.run(
        ctx.run_id, base_dir=ctx.base_dir,
        dispatch_allowed=ctx.dispatch_allowed,
        already_sent=already,
        adapter=ctx.extras.get("kakao_adapter"),
        routes=ctx.extras.get("routes"),
    )
    if not ctx.dispatch_allowed:
        return StageResult("S7", "skipped", note=f"발송 차단({ctx.mode}) — would_send {len(res.get('would_send', []))}")
    newly = res.get("newly_sent", [])
    ctx.state.setdefault("dispatch_log", []).extend(newly)  # 발송 즉시 기록(멱등)

    # 메일(Part A/B) — 발송 허용 시에만. 메일은 fail-soft(카톡 게이트와 별개)
    mail_note = ""
    try:
        mres = s7_mail.run(ctx.run_id, base_dir=ctx.base_dir,
                           base_url=ctx.params.get("base_url", ""),
                           out_dir=ctx.base_dir / ctx.run_id / "mail")
        mail_note = f" · 메일 {mres['meta']['part_a']}+{mres['meta']['part_b']}({mres['sender']})"
    except Exception as exc:  # 메일 실패는 카톡을 막지 않는다
        mail_note = f" · 메일 실패({type(exc).__name__})"

    return StageResult("S7", "success", output_count=len(newly),
                       note=f"카톡 {len(newly)} · 보류 {len(res.get('held', []))} · "
                            f"L0스킵 {len(res.get('l0_skipped', []))}{mail_note}")


def _s8_report(ctx: StageContext) -> StageResult:
    rep = build_report(ctx.state)
    (ctx.base_dir / ctx.run_id / "report.txt").write_text(rep, encoding="utf-8")
    print(rep)
    return StageResult("S8", "success", artifacts=[str(ctx.base_dir / ctx.run_id / "report.txt")])


def build_default_dag() -> list[Stage]:
    return [
        Stage("S0", _s0_preflight, FAIL_HARD),
        Stage("S1", _s1_collect, FAIL_SOFT),
        Stage("S2", _s2_normalize, FAIL_HARD),
        Stage("S3", _s3_fetch, FAIL_SOFT),
        Stage("S4", _s4_analyze, FAIL_SOFT),
        Stage("S4L1", _s4_l1, FAIL_SOFT),
        # S5 CLUSTER+SWOT(private)은 S7과 무의존인 형제 노드 — S7이 issues.json을 입력받지 못한다(INV-3)
        Stage("S5", _s5_swot, FAIL_SOFT),
        Stage("S6", _s6_publish, FAIL_HARD),
        Stage("S7", _s7_dispatch, FAIL_CLOSED),
        Stage("S8", _s8_report, FAIL_SOFT),
    ]


# ── 상태 파일 ────────────────────────────────────────────────────────────────

def state_dir() -> Path:
    # PNB_STATE_DIR 로 재정의 가능(테스트는 tmp 로 격리, 운영은 기본 pipeline/state)
    d = os.environ.get("PNB_STATE_DIR")
    return Path(d) if d else common.ROOT / "pipeline" / "state"


def state_path(run_id: str) -> Path:
    return state_dir() / f"run-{run_id}.json"


def load_state(run_id: str) -> dict[str, Any] | None:
    p = state_path(run_id)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def save_state(state: dict[str, Any]) -> None:
    p = state_path(state["run_id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 실행 ─────────────────────────────────────────────────────────────────────

def _done(status: str | None) -> bool:
    return status in ("success", "skipped")


def run_pipeline(ctx: StageContext, dag: list[Stage] | None = None) -> dict[str, Any]:
    dag = dag or build_default_dag()
    state = ctx.state
    only = ctx.params.get("only")
    resuming = ctx.params.get("resuming", False)

    for stage in dag:
        prior = (state.get("stages", {}).get(stage.name) or {}).get("status")
        # --only: 지정 스테이지만 실행
        if only and stage.name not in only:
            continue
        # resume: 이미 끝난 스테이지는 스킵
        if resuming and not only and _done(prior):
            continue

        t0 = time.time()
        try:
            res = stage.fn(ctx)
        except Exception as exc:  # 스테이지 전체 실패
            res = StageResult(stage.name, "failed", errors=[{"error_type": type(exc).__name__,
                                                             "message": str(exc)}])
        res.duration_sec = round(time.time() - t0, 3)

        state.setdefault("stages", {})[stage.name] = asdict(res)
        _accumulate_cost(state, res)
        save_state(state)

        if res.status == "failed" and stage.policy == FAIL_HARD:
            state["status"] = "failed"
            save_state(state)
            print(f"[orchestrator] {stage.name} fail-hard → 중단")
            return state

    # 종료 상태 판정
    stages = state.get("stages", {})
    if any(s.get("status") == "failed" for s in stages.values()):
        state["status"] = "partial"
    elif any(s.get("status") == "partial" for s in stages.values()):
        state["status"] = "partial"
    else:
        state["status"] = "success"
    save_state(state)
    return state


def _accumulate_cost(state: dict[str, Any], res: StageResult) -> None:
    tot = state.setdefault("cost_total", {"api_calls": 0, "usd": 0.0})
    tot["api_calls"] += res.cost.get("api_calls", 0)
    tot["usd"] = round(tot.get("usd", 0.0) + res.cost.get("usd", 0.0), 4)


def build_report(state: dict[str, Any]) -> str:
    stages = state.get("stages", {})
    lines = [f"[RUN {state['run_id']}] {state['mode']} · {state.get('status','?')}",
             f"💰 api_calls {state.get('cost_total',{}).get('api_calls',0)} · "
             f"${state.get('cost_total',{}).get('usd',0.0)}", ""]
    for name in ("S0", "S1", "S2", "S3", "S4", "S4L1", "S5", "S6", "S7", "S8"):
        s = stages.get(name)
        if not s:
            continue
        line = f"  {name:5} {s['status']:8} out={s.get('output_count',0)}"
        if s.get("errors"):
            line += f" ⚠️{len(s['errors'])}"
        if s.get("note"):
            line += f"  {s['note']}"
        lines.append(line)
    # analysis_level 통계 (S6 note 또는 articles.json)
    lines.append("")
    corr = state.get("axis_corrections_total")
    if corr is not None:
        flag = "  ⚠️ 프롬프트 점검 권장" if corr > 0 else ""
        lines.append(f"  SWOT 축 교정: {corr}건 (L2 오배치를 규칙이 교정){flag}")
    lines.append(f"  발송 로그: {len(state.get('dispatch_log', []))}건 (멱등 판정 기준)")
    warnings = [f"{n}: {len(s.get('errors', []))} errors" for n, s in stages.items() if s.get("errors")]
    if warnings:
        lines.append("  ⚠️ " + " · ".join(warnings))
    return "\n".join(lines)


def make_context(mode: Mode, run_id: str | None, *, resume: bool, only: list[str] | None,
                 no_dispatch: bool, params: dict[str, Any] | None = None,
                 base_dir: Path | None = None, data_dir: Path | None = None,
                 extras: dict[str, Any] | None = None) -> StageContext:
    run_id = run_id or common.make_run_id()
    base = base_dir or (common.ROOT / "raw")
    data = data_dir or (common.ROOT / "data")

    # backfill 은 발송 강제 차단 (docs §11.7)
    dispatch_allowed = mode not in ("dryrun", "backfill") and not no_dispatch

    state = (load_state(run_id) if resume else None) or {
        "run_id": run_id, "mode": mode, "started_at": common.now_kst().isoformat(),
        "status": "running", "params": params or {}, "stages": {},
        "cost_total": {"api_calls": 0, "usd": 0.0}, "dispatch_log": [],
    }
    p = dict(params or {})
    p["only"] = only
    p["resuming"] = resume
    return StageContext(run_id=run_id, base_dir=base, data_dir=data, mode=mode,
                        dispatch_allowed=dispatch_allowed, params=p, state=state,
                        extras=extras or {})


def main() -> None:
    ap = argparse.ArgumentParser(description="posco-news-bot 오케스트레이터")
    ap.add_argument("--mode", choices=["daily", "intraday", "dryrun", "backfill"], default="daily")
    ap.add_argument("--dry-run", action="store_true", help="발송 없이 전 과정 검증(=mode dryrun 상당)")
    ap.add_argument("--resume", metavar="RUN_ID", default=None)
    ap.add_argument("--only", default=None, help="쉼표구분 스테이지 (예: S4,S6,S7)")
    ap.add_argument("--no-dispatch", action="store_true")
    ap.add_argument("--since", default=None)
    ap.add_argument("--until", default=None)
    ap.add_argument("--max-queries", type=int, default=None)
    args = ap.parse_args()

    mode: Mode = "dryrun" if args.dry_run else args.mode
    only = [s.strip() for s in args.only.split(",")] if args.only else None
    params = {"since": args.since, "until": args.until, "max_queries": args.max_queries}

    ctx = make_context(mode, args.resume, resume=bool(args.resume), only=only,
                       no_dispatch=args.no_dispatch, params=params)
    if args.mode == "backfill" and ctx.dispatch_allowed:
        raise SystemExit("backfill 은 발송이 차단되어야 한다")  # 방어
    print(f"[orchestrator] run_id={ctx.run_id} mode={mode} dispatch={'ON' if ctx.dispatch_allowed else 'OFF'}")
    state = run_pipeline(ctx)
    raise SystemExit(0 if state["status"] in ("success", "partial") else 1)


if __name__ == "__main__":
    main()
