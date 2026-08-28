"""P7 (오케스트레이터) 검증 — ROADMAP.md 완료기준 4개.

  ① 중간 실패 후 --resume 성공
  ② PC 꺼진 상태(L1/L2 없이) L0 단독 발행 성공
  ③ 재실행 시 중복 발송 없음 (dispatch_log 멱등)
  ④ --mode backfill 이 발송 강제 차단
  + 네트워크·키 없이 전체 DAG dry-run 완주
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import orchestrator as orch
from pipeline.orchestrator import Stage, StageResult, FAIL_HARD, FAIL_SOFT, make_context, run_pipeline
from pipeline.stages import common, s7_dispatch

VALID_BODY = (
    "[뉴스토마토] 캐나다에 현지 생산 기반을 구축 중인 배터리 업계는 양국의 통상 갈등 확대 "
    "가능성을 주시하고 있습니다. 현재 LG에너지솔루션(373220)은 캐나다 온타리오주에 배터리 "
    "생산법인 '넥스트스타 에너지'를 운영 중이고, 포스코퓨처엠은 퀘백주에 GM과 함께 양극재 "
    "합작사 '얼티엄캠'을 설립하고 연산 3만톤 규모의 생산기지를 짓고 있습니다."
)


class UnavailableClient:
    """Ollama 미응답 시뮬레이션 (PC 꺼짐)."""
    def available(self):
        return False
    def generate(self, prompt):
        raise AssertionError("호출되면 안 됨")


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    d = ROOT / "pipeline" / "state"
    if d.exists():
        for p in d.glob("run-testp7-*.json"):
            p.unlink()


def seed_collected(base, run_id, rows):
    common.write_jsonl(base / run_id / "collected.jsonl", rows)


def posco_collected():
    return [
        {"title": "포스코퓨처엠 광양 양극재 증설", "url": "https://ex.com/1",
         "description": "포스코퓨처엠이 광양 양극재 공장을 증설한다", "source": "google",
         "source_type": "news", "lang": "ko", "track": "posco", "category": "futurem",
         "published_at": common.now_kst().isoformat(), "outlet": "연합뉴스"},
        {"title": "LG엔솔 유럽 수주", "url": "https://ex.com/2",
         "description": "LG에너지솔루션 유럽 완성차 수주", "source": "google",
         "source_type": "news", "lang": "ko", "track": "battery", "category": "cell-kr",
         "published_at": common.now_kst().isoformat(), "outlet": "이데일리"},
    ]


# ── ① 중간 실패 후 resume ────────────────────────────────────────────────────

def test_resume_after_midfailure(tmp_path):
    run_id = "testp7-resume"
    calls = {"A": 0, "B": 0, "C": 0}

    def A(ctx):
        calls["A"] += 1
        return StageResult("A", "success")

    def B(ctx):
        calls["B"] += 1
        if calls["B"] == 1:
            raise RuntimeError("의도된 중간 실패")
        return StageResult("B", "success")

    def C(ctx):
        calls["C"] += 1
        return StageResult("C", "success")

    dag = [Stage("A", A, FAIL_HARD), Stage("B", B, FAIL_HARD), Stage("C", C, FAIL_SOFT)]

    ctx = make_context("daily", run_id, resume=False, only=None, no_dispatch=True,
                       base_dir=tmp_path, data_dir=tmp_path)
    st = run_pipeline(ctx, dag)
    assert st["status"] == "failed"
    assert st["stages"]["B"]["status"] == "failed"
    assert "C" not in st["stages"]          # fail-hard → C 미실행

    # resume — A 는 스킵, B 재실행 성공, C 실행
    ctx2 = make_context("daily", run_id, resume=True, only=None, no_dispatch=True,
                        base_dir=tmp_path, data_dir=tmp_path)
    st2 = run_pipeline(ctx2, dag)
    assert st2["status"] == "success"
    assert calls["A"] == 1                   # A 재실행 안 됨(멱등 스킵)
    assert calls["B"] == 2                   # B 만 재시도
    assert calls["C"] == 1


# ── ② PC 꺼진 상태 — L0 단독 발행 ────────────────────────────────────────────

def test_l0_only_publish_when_pc_off(tmp_path):
    run_id = "testp7-l0"
    base = tmp_path / "raw"
    data = tmp_path / "data"
    seed_collected(base, run_id, posco_collected())

    ctx = make_context("dryrun", run_id, resume=False, only=["S2", "S4", "S4L1", "S6"],
                       no_dispatch=True, base_dir=base, data_dir=data,
                       extras={"llm_client": UnavailableClient()})
    st = run_pipeline(ctx)

    assert st["stages"]["S4L1"]["status"] == "skipped"     # Ollama 없음 → L1 스킵
    assert st["stages"]["S6"]["status"] == "success"
    payload = json.loads((data / "articles.json").read_text(encoding="utf-8"))
    assert payload["counts"]["total"] == 2                 # L0만으로 발행됨
    assert all(a["analysis_level"] == "L0" for a in payload["articles"])
    assert all(a.get("summary") for a in payload["articles"])
    # 금지 필드 누출 없음
    assert not any(k in a for a in payload["articles"] for k in ("body", "kakao_summary", "swot_axis"))


# ── ③ dispatch_log 멱등 (중복 발송 없음) ────────────────────────────────────

ENABLED_KAKAO = {
    "id": "kakao-team", "channel": "kakao", "enabled": True, "room_id_env": "",
    "filter": {"any_of": [{"posco_relevance": "primary"}]},
    "guards": {"require_relevance": True, "summary_len": [150, 350]},
    "daily_limit": 8,
}


def sendable_article():
    return {
        "id": "send1", "title": "포스코퓨처엠 기사", "url": "https://ex.com/s1",
        "thumbnail": "https://ex.com/t.jpg", "subtitle": "부제", "outlet": "뉴스토마토",
        "posco_relevance": "primary", "impact": "high", "prescore": 6.0,
        "summary_method": "generative", "kakao_summary": VALID_BODY,
    }


def test_dispatch_log_idempotent(tmp_path):
    run_id = "testp7-dedup"
    base = tmp_path / "raw"
    common.write_jsonl(base / run_id / "l1.jsonl", [sendable_article()])
    adapter = s7_dispatch.RecordingKakaoAdapter()

    # 1차 발송
    ctx = make_context("daily", run_id, resume=False, only=["S7"], no_dispatch=False,
                       base_dir=base, data_dir=tmp_path,
                       extras={"kakao_adapter": adapter, "routes": [ENABLED_KAKAO]})
    st = run_pipeline(ctx)
    assert st["stages"]["S7"]["status"] == "success"
    assert st["dispatch_log"] == ["send1"]
    assert len(adapter.sent) == 1

    # 2차 재실행 — 이미 보낸 건은 스킵(중복 발송 없음)
    ctx2 = make_context("daily", run_id, resume=True, only=["S7"], no_dispatch=False,
                        base_dir=base, data_dir=tmp_path,
                        extras={"kakao_adapter": adapter, "routes": [ENABLED_KAKAO]})
    st2 = run_pipeline(ctx2)
    assert st2["dispatch_log"] == ["send1"]        # 중복 append 없음
    assert len(adapter.sent) == 1                  # 실제 발송도 1회뿐


# ── ④ backfill 발송 차단 ─────────────────────────────────────────────────────

def test_backfill_blocks_dispatch(tmp_path):
    run_id = "testp7-backfill"
    base = tmp_path / "raw"
    common.write_jsonl(base / run_id / "l1.jsonl", [sendable_article()])
    adapter = s7_dispatch.RecordingKakaoAdapter()

    ctx = make_context("backfill", run_id, resume=False, only=["S7"], no_dispatch=False,
                       base_dir=base, data_dir=tmp_path,
                       extras={"kakao_adapter": adapter, "routes": [ENABLED_KAKAO]})
    assert ctx.dispatch_allowed is False            # backfill → 발송 강제 차단
    st = run_pipeline(ctx)
    assert st["stages"]["S7"]["status"] == "skipped"
    assert adapter.sent == []                       # 실제 발송 0
    assert st.get("dispatch_log", []) == []


# ── 전체 DAG dry-run 완주 (네트워크·키 없음) ────────────────────────────────

def test_full_dag_dryrun_completes(tmp_path):
    run_id = "testp7-full"
    base = tmp_path / "raw"
    data = tmp_path / "data"
    seed_collected(base, run_id, posco_collected())

    # S1(수집)은 네트워크라 건너뛰도록 상태에 성공 표시 후 resume
    orch.save_state({"run_id": run_id, "mode": "dryrun", "status": "running",
                     "params": {}, "stages": {"S1": {"status": "success", "output_count": 2}},
                     "cost_total": {"api_calls": 0, "usd": 0.0}, "dispatch_log": []})

    ctx = make_context("dryrun", run_id, resume=True, only=None, no_dispatch=False,
                       base_dir=base, data_dir=data,
                       extras={"llm_client": UnavailableClient()})
    assert ctx.dispatch_allowed is False            # dryrun → 발송 OFF
    st = run_pipeline(ctx)

    # 모든 스테이지가 종료 상태에 도달(크래시 없이 완주)
    for name in ("S0", "S2", "S3", "S4", "S4L1", "S6", "S7", "S8"):
        assert st["stages"][name]["status"] in ("success", "partial", "skipped")
    assert st["stages"]["S1"]["status"] == "success"   # resume 로 스킵 유지
    assert st["stages"]["S7"]["status"] == "skipped"   # dryrun 발송 차단
    assert (data / "articles.json").exists()
    assert st["status"] in ("success", "partial")
