"""P5a/b (정책·통상 보드) 검증 — L0 stager + 엔티티 관리.

완료기준(합성 케이스):
  ① Federal Register "Proposed Rule" → proposed (뉴스 없이도)
  ② 관보 행정예고 → proposed
  ③ 뉴스 단독 "검토 중" → discussion (proposed 로 승격 안 됨)
  ④ 흑연 수출통제 → affects_futurem=true (음극재 원료)
  ⑤ 철강 관세 → affects_futurem=false
  + 같은 정책에 기사 여러 건 → 타임라인 중복 없이 누적
  + board 축약본에 our_position·policy_ask 부재
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.stages import stagers

KW = stagers.common.load_keywords()


def parti(aid, title, source_type="news", country="US", topic="45X", date="2026-08-27", track="policy"):
    return {"id": aid, "title": title, "summary": "", "track": track,
            "countries": [country], "topics": [topic], "category": "pol-us",
            "date": date, "source_type": source_type}


# ── ① Federal Register Proposed Rule → proposed (뉴스 없이도) ────────────────

def test_case1_federal_register_proposed_rule():
    assert stagers.classify_policy_stage("US Treasury issues Proposed Rule on 45X", "gazette") == "proposed"
    pols = stagers.build_policies([parti("f1", "Proposed Rule on 45X anode", source_type="gazette")], keywords=KW)
    assert pols[0]["current_stage"] == "proposed"


# ── ② 관보 행정예고 → proposed ──────────────────────────────────────────────

def test_case2_gazette_admin_notice():
    assert stagers.classify_policy_stage("화학물질관리법 시행령 행정예고", "gazette") == "proposed"


# ── ③ 뉴스 단독 "검토 중" → discussion (승격 안 됨) ─────────────────────────

def test_case3_news_under_review_stays_discussion():
    assert stagers.classify_policy_stage("정부가 이차전지 지원 방안을 검토 중이다", "news") == "discussion"
    pols = stagers.build_policies([parti("n1", "정부, 배터리 지원 방안 검토 중", source_type="news")], keywords=KW)
    assert pols[0]["current_stage"] == "discussion"      # proposed 로 승격되지 않음


# ── ④⑤ affects_futurem ─────────────────────────────────────────────────────

def test_case4_graphite_affects_futurem():
    assert stagers.affects_futurem("중국, 흑연 수출통제 예비판정", KW) is True
    assert "흑연" in stagers.matched_materials("중국 흑연 수출통제", KW)


def test_case5_steel_tariff_not_affects():
    assert stagers.affects_futurem("미국, 철강 관세 25% 부과", KW) is False


# ── 분쟁 stager ─────────────────────────────────────────────────────────────

def test_dispute_stager():
    assert stagers.classify_dispute_stage("반덤핑 예비판정 발표", "news") == "preliminary"
    assert stagers.classify_dispute_stage("관세 관련 동향", "news") == "initiated"  # 기본값


def test_dispute_affects_graphite_vs_steel():
    graphite = stagers.build_disputes(
        [{"id": "g1", "title": "중국 흑연 수출통제 발효", "summary": "", "track": "trade",
          "countries": ["CN", "KR"], "topics": ["흑연 수출허가"], "category": "trade-export",
          "date": "2026-08-27", "source_type": "gazette"}], keywords=KW)
    assert graphite[0]["affects_futurem"] is True
    assert graphite[0]["current_stage"] == "in_force"
    steel = stagers.build_disputes(
        [{"id": "s1", "title": "미국 철강 관세 부과", "summary": "", "track": "trade",
          "countries": ["US", "CA"], "topics": ["관세"], "category": "trade-tariff",
          "date": "2026-08-27", "source_type": "news"}], keywords=KW)
    assert steel[0]["affects_futurem"] is False


# ── 타임라인 중복 없이 누적 ─────────────────────────────────────────────────

def test_timeline_accumulates_without_duplicates():
    a1 = parti("a1", "45X 개정안 입법예고", source_type="gazette", date="2026-08-01")
    a2 = parti("a2", "45X 개정안 의견수렴 진행", source_type="news", date="2026-08-10")
    a3 = parti("a3", "45X 최종규칙 공포", source_type="gazette", date="2026-08-20")
    pols = stagers.build_policies([a1, a2, a3], keywords=KW)
    assert len(pols) == 1                                # 같은 정책(us-45x)
    p = pols[0]
    assert len(p["timeline"]) == 3                       # 기사 3건 = 이벤트 3건
    assert p["current_stage"] == "enacted"               # 최신(공포)
    assert [e["date"] for e in p["timeline"]] == ["2026-08-01", "2026-08-10", "2026-08-20"]

    # 재실행: 같은 기사 다시 넣어도 타임라인 중복 없음
    again = stagers.build_policies([a1], existing=pols, keywords=KW)
    assert len(again[0]["timeline"]) == 3                # 늘지 않음


# ── board 축약본: 민감 필드 제거 ────────────────────────────────────────────

def test_board_strips_sensitive_fields():
    pols = stagers.build_policies([parti("x1", "45X 입법예고", source_type="gazette")], keywords=KW)
    pols[0]["our_position"] = "제12조 음극재 포함 요청"    # L2 필드 주입
    pols[0]["policy_ask"] = "적격비용 명확화"
    board = stagers.policy_board(pols)
    b = board[0]
    for f in ("our_position", "policy_ask", "affects_futurem", "affects"):
        assert f not in b, f"board(L1)에 민감 필드 {f} 누출"
    assert b["current_stage"] == "proposed"              # 비민감 정보는 유지
    assert "timeline" in b


def test_pin_by_affects_puts_futurem_first():
    a = {"dispute_id": "d1", "affects_futurem": False, "last_updated": "2026-08-27"}
    b = {"dispute_id": "d2", "affects_futurem": True, "last_updated": "2026-08-20"}
    pinned = stagers.pin_by_affects([a, b])
    assert pinned[0]["dispute_id"] == "d2"               # affects=True 상단 고정
