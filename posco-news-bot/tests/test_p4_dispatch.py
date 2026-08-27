"""P4 (발송 + 안전장치) 검증 — ROADMAP.md 완료기준 중 코드 검증 가능한 6개.

  ① 라우트별 필터 테스트 통과
  ② 포스코 미언급 기사가 카톡에 나가지 않음
  ③ tone=crisis 건이 자동 발송되지 않고 보류됨
  ④ 킬 스위치(enabled:false) 즉시 반영
  ⑤ validate_kakao() 골든 샘플 회귀 테스트 통과
  ⑥ 포맷 위반 시 해당 건만 미발송, 나머지는 정상 발송
  (섀도 운영 1주는 실운영 — 제외)

추가: INV-6 — L0 추출 요약만 있는 건은 카톡 스킵 + 건수 기록.
"""
from __future__ import annotations

import copy
import pathlib
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.stages import s7_dispatch as dispatch
from pipeline.stages.kakao_format import validate_kakao

ROUTES = yaml.safe_load((ROOT / "pipeline/dispatch_routes.yaml").read_text(encoding="utf-8"))["routes"]
KAKAO = next(r for r in ROUTES if r["id"] == "kakao-team")
ENTITIES = ["포스코", "포스코퓨처엠", "POSCO"]

VALID_BODY = (
    "[뉴스토마토] 캐나다에 현지 생산 기반을 구축 중인 배터리 업계는 양국의 통상 갈등 확대 "
    "가능성을 주시하고 있습니다. 현재 LG에너지솔루션(373220)은 캐나다 온타리오주에 배터리 "
    "생산법인 '넥스트스타 에너지'를 운영 중이고, 포스코퓨처엠은 퀘백주에 GM과 함께 양극재 "
    "합작사 '얼티엄캠'을 설립하고 연산 3만톤 규모의 생산기지를 짓고 있습니다."
)


def article(**kw):
    base = {
        "id": "a1", "title": "포스코퓨처엠 관련 기사", "url": "https://news.co/1",
        "thumbnail": "https://news.co/t.jpg", "subtitle": "부제",
        "outlet": "뉴스토마토", "posco_relevance": "primary", "impact": "high",
        "prescore": 6.0, "summary_method": "generative", "kakao_summary": VALID_BODY,
    }
    base.update(kw)
    return base


def plan(articles, route=KAKAO, **kw):
    return dispatch.plan_kakao(articles, route, entities=ENTITIES, **kw)


# ── ① 라우트별 필터 ─────────────────────────────────────────────────────────

def test_route_filters():
    kf = KAKAO["filter"]
    assert dispatch.match_filter({"posco_relevance": "primary"}, kf)               # primary ✓
    assert dispatch.match_filter({"posco_relevance": "mention", "impact": "high"}, kf)  # mention+high ✓
    assert dispatch.match_filter({"posco_relevance": "mention", "impact": "mid"}, kf)   # mention+mid ✓
    assert not dispatch.match_filter({"posco_relevance": "mention", "impact": "low"}, kf)  # mention+low ✗
    assert not dispatch.match_filter({"posco_relevance": "none"}, kf)              # none ✗

    tg_ind = next(r for r in ROUTES if r["id"] == "tg-industry")["filter"]
    assert dispatch.match_filter({"track": "battery"}, tg_ind)
    assert not dispatch.match_filter({"track": "posco"}, tg_ind)
    # filter 없는 조건 → 발송 안 함 (fail-closed)
    assert not dispatch.match_filter({"posco_relevance": "primary"}, None)


# ── ② 포스코 미언급 기사가 카톡에 안 나감 ───────────────────────────────────

def test_none_relevance_not_sent():
    arts = [article(id="x", posco_relevance="none")]
    p = plan(arts)
    sent_ids = [a["id"] for _, _, a in p.to_send]
    assert "x" not in sent_ids
    assert p.counts()["to_send"] == 0


# ── ③ crisis 보류 ───────────────────────────────────────────────────────────

def test_crisis_is_held_not_sent():
    arts = [article(id="c", tone="crisis")]
    p = plan(arts)
    assert [i for i, _ in p.held] == ["c"]
    assert p.counts()["to_send"] == 0


# ── ④ 킬 스위치 ─────────────────────────────────────────────────────────────

def test_kill_switch_blocks_all():
    arts = [article(id="k1"), article(id="k2")]
    p = plan(arts)
    assert p.counts()["to_send"] == 2  # 계획상으로는 발송 대상

    adapter = dispatch.RecordingKakaoAdapter()
    # enabled:false (기본) → 어댑터 호출조차 안 됨
    rep = dispatch.dispatch_kakao(p, KAKAO, adapter, room_id="R")
    assert rep.enabled is False
    assert rep.sent == []
    assert adapter.sent == []  # 실제 발송 0

    # enabled:true 로 뒤집으면 발송된다 (한 줄로 즉시 반영)
    on = copy.deepcopy(KAKAO); on["enabled"] = True
    rep2 = dispatch.dispatch_kakao(p, on, adapter, room_id="R")
    assert rep2.enabled is True
    assert set(rep2.sent) == {"k1", "k2"}
    assert len(adapter.sent) == 2


# ── ⑤ validate_kakao 골든 회귀 (+ 계획 흐름 통과) ───────────────────────────

GOLDEN_CARD = {
    "thumbnail": "https://example.com/thumb.jpg",
    "title": "미·캐나다 '관세전쟁' 불똥?…산업계 '촉각'",
    "description": "미·캐나다 북미 생산거점 관세 부담 가능성",
    "link": "https://www.newstomato.com/ReadNews.aspx?no=1234567",
}


def test_golden_sample_passes_and_flows():
    assert validate_kakao(GOLDEN_CARD, VALID_BODY, entities=ENTITIES) == []
    p = plan([article(id="g")])
    assert [a["id"] for _, _, a in p.to_send] == ["g"]


# ── ⑥ 포맷 위반 건만 제외, 나머지 정상 ──────────────────────────────────────

def test_format_violation_excludes_only_that_one():
    good = article(id="good")
    bad = article(id="bad", kakao_summary=VALID_BODY.replace("짓고 있습니다.", "지었다."))  # 반말 종결
    on = copy.deepcopy(KAKAO); on["enabled"] = True
    p = plan([good, bad], route=on)

    assert [a["id"] for _, _, a in p.to_send] == ["good"]
    assert [i for i, _ in p.excluded] == ["bad"]

    adapter = dispatch.RecordingKakaoAdapter()
    rep = dispatch.dispatch_kakao(p, on, adapter, room_id="R")
    assert rep.sent == ["good"]              # 나머지는 정상 발송
    assert len(adapter.sent) == 1            # 전체 중단 아님


# ── INV-6: L0 추출 요약만 있는 건은 스킵 + 건수 ─────────────────────────────

def test_extractive_only_skipped_with_count():
    arts = [
        article(id="l0", summary_method="extractive"),   # L0만 → 스킵
        article(id="l1", summary_method="generative"),   # L1 생성요약 → 발송
    ]
    p = plan(arts)
    assert p.l0_skipped == ["l0"]
    assert [a["id"] for _, _, a in p.to_send] == ["l1"]
    assert p.counts()["l0_skipped"] == 1


# ── 부가: 중복 발송 방지 · 일일 상한 ────────────────────────────────────────

def test_dedup_and_daily_limit():
    p = plan([article(id="dup")], already_sent={"dup"})
    assert p.deduped == ["dup"]

    on = copy.deepcopy(KAKAO); on["enabled"] = True; on["daily_limit"] = 2
    many = [article(id=f"n{i}", prescore=float(i)) for i in range(5)]
    p2 = dispatch.plan_kakao(many, on, entities=ENTITIES)
    assert p2.counts()["to_send"] == 2
    assert len(p2.overflow_dropped) == 3
    # 선정은 prescore 상위 우선
    assert {a["id"] for _, _, a in p2.to_send} == {"n4", "n3"}
