"""s4_l1 (Ollama L1 생성 요약) 검증 — 모의 클라이언트로 Ollama 없이 구조 검증.

핵심:
  - 생성 결과를 validate_body 로 자체 검증
  - 실패 시 재시도 1회 → 그래도 실패면 L0 유지(summary_method=extractive 그대로)
  - Ollama 미응답이면 전체 스킵, L0 유지 (INV-6)
  - 성공 시 kakao_summary + tone + summary_method=generative → 카톡 발송 자격
"""
from __future__ import annotations

import json
import pathlib
import sys
import urllib.error

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.stages import s4_l1
from pipeline.stages import s7_dispatch
from pipeline.stages.kakao_format import validate_body

ENTITIES = ["포스코", "포스코퓨처엠", "POSCO"]

VALID_BODY = (
    "[뉴스토마토] 캐나다에 현지 생산 기반을 구축 중인 배터리 업계는 양국의 통상 갈등 확대 "
    "가능성을 주시하고 있습니다. 현재 LG에너지솔루션(373220)은 캐나다 온타리오주에 배터리 "
    "생산법인 '넥스트스타 에너지'를 운영 중이고, 포스코퓨처엠은 퀘백주에 GM과 함께 양극재 "
    "합작사 '얼티엄캠'을 설립하고 연산 3만톤 규모의 생산기지를 짓고 있습니다."
)
BAD_BODY = "[뉴스토마토] 포스코퓨처엠이 공장을 지었다."  # 짧음 + 반말 종결


class MockClient:
    """generate 응답을 큐로 주입. available 로 Ollama 가용 여부 시뮬레이션."""

    def __init__(self, responses, is_available=True, raise_on_generate=False):
        self._responses = list(responses)
        self._available = is_available
        self._raise = raise_on_generate
        self.calls = 0

    def available(self):
        return self._available

    def generate(self, prompt):
        self.calls += 1
        if self._raise:
            raise urllib.error.URLError("connection refused")
        return self._responses.pop(0) if self._responses else "{}"


def article(**kw):
    base = {
        "id": "a1", "title": "포스코퓨처엠 관련 기사", "outlet": "뉴스토마토",
        "url": "https://news.co/1", "thumbnail": "https://news.co/t.jpg", "subtitle": "부제",
        "summary": "포스코퓨처엠이 캐나다에 공장을 지었다.", "summary_method": "extractive",
        "posco_relevance": "primary", "impact": "high", "analysis_level": "L0",
    }
    base.update(kw)
    return base


def resp(aid="a1", body=VALID_BODY, tone="neutral"):
    return json.dumps({"id": aid, "kakao_summary": body, "tone": tone})


# ── 자체 검증 전제 ──────────────────────────────────────────────────────────

def test_valid_body_passes_bad_fails():
    assert validate_body(VALID_BODY, ENTITIES) == []
    assert validate_body(BAD_BODY, ENTITIES)


# ── 성공 ────────────────────────────────────────────────────────────────────

def test_generate_ok_sets_generative_and_tone():
    a, status = s4_l1.enrich_one(article(), MockClient([resp(tone="negative")]), ENTITIES)
    assert status == "ok"
    assert a["kakao_summary"] == VALID_BODY
    assert a["summary_method"] == "generative"   # 카톡 발송 자격
    assert a["tone"] == "negative"
    assert a["analysis_level"] == "L1"


# ── 재시도 1회 후 성공 ──────────────────────────────────────────────────────

def test_retry_once_then_ok():
    client = MockClient([resp(body=BAD_BODY), resp(body=VALID_BODY)])
    a, status = s4_l1.enrich_one(article(), client, ENTITIES)
    assert status == "ok"
    assert client.calls == 2                      # 첫 실패 → 재시도


# ── 검증 미달 → L0 유지 ─────────────────────────────────────────────────────

def test_l1_failed_keeps_l0():
    client = MockClient([resp(body=BAD_BODY), resp(body=BAD_BODY)])
    a, status = s4_l1.enrich_one(article(), client, ENTITIES)
    assert status == "l1_failed"
    assert "kakao_summary" not in a
    assert a["summary_method"] == "extractive"    # L0 유지 (INV-6)
    assert a["l1_reject"]                          # 사유 기록


# ── 호출 실패 → L0 유지 ─────────────────────────────────────────────────────

def test_generate_error_keeps_l0():
    a, status = s4_l1.enrich_one(article(), MockClient([], raise_on_generate=True), ENTITIES)
    assert status == "error"
    assert a["summary_method"] == "extractive"


# ── id echo 불일치 → 무효 처리 ──────────────────────────────────────────────

def test_id_echo_mismatch_rejected():
    client = MockClient([resp(aid="WRONG"), resp(aid="WRONG")])
    a, status = s4_l1.enrich_one(article(), client, ENTITIES)
    assert status == "l1_failed"                   # id 불일치 → 파싱 무효 → 재시도 후 실패


# ── Ollama 미응답 → 전체 스킵, L0 유지 (INV-6) ──────────────────────────────

def test_unavailable_skips_all():
    arts = [article(id="x"), article(id="y", posco_relevance="none")]
    result = s4_l1.enrich([*arts], MockClient([], is_available=False), ENTITIES)
    assert result["available"] is False
    assert result["stats"]["skipped"] == 2
    assert all(a["summary_method"] == "extractive" for a in result["articles"])


# ── 대상 선별: posco_relevance none 은 L1 대상 아님 ─────────────────────────

def test_none_relevance_not_enriched():
    arts = [article(id="p", posco_relevance="primary"),
            article(id="n", posco_relevance="none")]
    result = s4_l1.enrich(arts, MockClient([resp(aid="p")]), ENTITIES)
    assert result["stats"]["ok"] == 1
    assert result["stats"]["not_target"] == 1


# ── L1 → 발송 연결: 생성 성공 건은 카톡 to_send, 실패 건은 l0_skipped ────────

def test_l1_output_flows_to_dispatch():
    good = article(id="g")
    bad = article(id="b")
    result = s4_l1.enrich(
        [good, bad],
        MockClient([resp(aid="g"), resp(aid="b", body=BAD_BODY), resp(aid="b", body=BAD_BODY)]),
        ENTITIES,
    )
    route = {"id": "kakao-team", "enabled": True,
             "filter": {"any_of": [{"posco_relevance": "primary"}]},
             "guards": {"require_relevance": True, "summary_len": [150, 350]},
             "daily_limit": 8}
    plan = s7_dispatch.plan_kakao(result["articles"], route, entities=ENTITIES)
    assert [a["id"] for _, _, a in plan.to_send] == ["g"]   # L1 성공 건만 발송
    assert plan.l0_skipped == ["b"]                          # L1 실패 → L0 → 카톡 스킵
