"""P2 L0 계층 (s4_analyze) 검증 — 크롤러 없이 결정론 규칙만.

검증 대상:
  - 추출 요약 (리드 문장, method=extractive, body>description>title degrade)
  - 규칙 태깅: companies / countries / topics / facets / source_type
  - policy_stage(T3) / dispute_stage(T4) 규칙, affects_futurem, impact_l0
  - INV-6: L0 산출물만으로 아카이브 필드가 완성 (summary·tags 존재)
  - INV-3/5: L2 비공개 필드·body 미방출
  - INV-1: 트랙 분기 없이 동일 함수가 처리
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.stages import common, s4_analyze  # noqa: E402

KW = common.load_keywords()

L2_FORBIDDEN = {"body", "futurem_implication", "swot_axis", "sector_impact",
                "frame", "tone_evidence", "policy_ask_hint", "fact_check_flags"}


def norm(**kw):
    base = {
        "id": "2026-08-27-abc0000000", "date": "2026-08-27",
        "published_at": "2026-08-27T06:00:00+09:00",
        "title": "제목", "title_slug": "t", "outlet": None, "outlet_tier": 3,
        "url": "https://ex.com/1", "canonical_url": "https://ex.com/1",
        "sources": ["google"], "lang": "ko", "track": "battery",
        "also_tracks": [], "track_ambiguous": False, "category": "mat-kr",
        "posco_relevance": "none", "prescore": 3.0, "dedup_of": None, "dup_count": 0,
        "description": "",
    }
    base.update(kw)
    return base


# ── 추출 요약 ──────────────────────────────────────────────────────────────

def test_extractive_summary_prefers_body_then_description():
    r = s4_analyze.extract_summary(
        body="첫 문장이다. 둘째 문장이다. 셋째 문장이다. 넷째 문장이다.",
        description="스니펫", title="제목")
    assert r["summary_method"] == "extractive"
    assert r["summary_source"] == "body"
    assert r["summary"] == "첫 문장이다. 둘째 문장이다."   # 리드 2문장
    assert len(r["bullets"]) == 4

    r2 = s4_analyze.extract_summary(body=None, description="스니펫 한 문장.", title="제목")
    assert r2["summary_source"] == "description"

    r3 = s4_analyze.extract_summary(body=None, description="", title="제목만 있음")
    assert r3["summary_source"] == "title"
    assert r3["summary"] == "제목만 있음"


# ── 규칙 태깅 ──────────────────────────────────────────────────────────────

def test_tagging_companies_countries_topics_facets():
    rec = norm(track="battery", category="cell-kr",
               title="LG에너지솔루션·삼성SDI 유럽 증설",
               description="LG엔솔과 삼성SDI가 유럽 공장 증설과 ESS 수주를 발표했다")
    out = s4_analyze.analyze_one(rec, KW)
    assert "LG에너지솔루션" in out["companies"]
    assert "삼성SDI" in out["companies"]
    assert "EU" in out["countries"]
    assert "증설" in out["topics"] and "ESS" in out["topics"]
    assert "track:battery" in out["facets"] and "cat:cell-kr" in out["facets"]
    assert "country:EU" in out["facets"]
    assert "company:LG에너지솔루션" in out["facets"]


def test_source_type_gazette_and_press():
    g = s4_analyze.analyze_one(norm(track="policy", category="pol-us", lang="en",
                                    outlet="Federal Register", title="Proposed Rule on 45X"), KW)
    assert g["source_type"] == "gazette"
    p = s4_analyze.analyze_one(norm(track="policy", category="pol-kr", outlet="정책브리핑",
                                    title="산업부 지원 발표"), KW)
    assert p["source_type"] == "press_release"
    n = s4_analyze.analyze_one(norm(outlet="연합뉴스", title="일반 기사"), KW)
    assert n["source_type"] == "news"


# ── policy_stage / dispute_stage ──────────────────────────────────────────

def test_policy_stage_rules():
    proposed = s4_analyze.analyze_one(norm(track="policy", category="pol-law",
                                           title="화학물질관리법 시행령 개정안 입법예고"), KW)
    assert proposed["policy_stage"] == "proposed"    # 예고 → 선제 대응 단계
    enacted = s4_analyze.analyze_one(norm(track="policy", category="pol-kr",
                                          title="이차전지 특별법 공포"), KW)
    assert enacted["policy_stage"] == "enacted"
    # 신호 없는 정책 뉴스 → discussion 기본값 (P1-2)
    disc = s4_analyze.analyze_one(norm(track="policy", category="pol-kr",
                                       title="배터리 지원 방안 논의"), KW)
    assert disc["policy_stage"] == "discussion"
    # 정책 아닌 트랙은 policy_stage None
    assert s4_analyze.analyze_one(norm(track="battery", category="cell-kr"), KW)["policy_stage"] is None


def test_dispute_stage_rules():
    prelim = s4_analyze.analyze_one(norm(track="trade", category="trade-remedy",
                                         title="반덤핑 예비판정 발표"), KW)
    assert prelim["dispute_stage"] == "preliminary"   # 대응 골든타임
    # 신호 없는 통상 뉴스 → initiated 기본값 (P1-9)
    init = s4_analyze.analyze_one(norm(track="trade", category="trade-tariff",
                                       title="관세 관련 동향"), KW)
    assert init["dispute_stage"] == "initiated"
    assert s4_analyze.analyze_one(norm(track="battery", category="cell-kr"), KW)["dispute_stage"] is None


def test_affects_futurem_and_impact():
    r = s4_analyze.analyze_one(norm(track="policy", category="pol-us", lang="en",
                                    outlet="Federal Register",
                                    title="45X anode cost 개정안 공고",
                                    description="음극재 적격비용 축소"), KW)
    assert r["affects_futurem"] is True               # 음극재 매칭
    assert r["policy_stage"] == "proposed"
    assert r["impact"] == "high"                      # proposed + affects_futurem


# ── INV 준수 ──────────────────────────────────────────────────────────────

def test_inv6_l0_only_archive_complete():
    """L0 산출물만으로 카드에 필요한 필드가 채워진다."""
    out = s4_analyze.analyze_one(norm(title="포스코퓨처엠 양극재 증설",
                                      description="포스코퓨처엠이 광양에 양극재 공장을 증설한다",
                                      track="posco", category="futurem",
                                      posco_relevance="primary"), KW)
    for f in ("summary", "bullets", "companies", "topics", "facets", "impact", "analysis_level"):
        assert f in out and out[f] is not None
    assert out["analysis_level"] == "L0"
    assert out["summary"]                              # 비어있지 않음


def test_inv3_inv5_no_l2_or_body_fields():
    """L2 비공개 필드·body 는 방출되지 않는다 (금지 필드가 입력에 섞여 있어도)."""
    poisoned = norm(title="테스트", body="원문 전문 절대 노출 금지",
                    swot_axis="T", futurem_implication="누출", sector_impact="direct")
    out = s4_analyze.analyze_one(poisoned, KW)
    assert not (set(out) & L2_FORBIDDEN)               # 교집합 없음


def test_inv1_single_path_all_tracks():
    """동일 함수가 4트랙을 처리하고 각기 요약·태깅을 산출한다."""
    for track, cat in [("posco", "futurem"), ("battery", "cell-kr"),
                       ("policy", "pol-us"), ("trade", "trade-tariff")]:
        out = s4_analyze.analyze_one(norm(track=track, category=cat,
                                          title="테스트 기사 제목", description="본문 요약 문장이다."), KW)
        assert out["analysis_level"] == "L0"
        assert out["summary_method"] == "extractive"
        assert "summary" in out


# ── 스테이지 파일 통신 + 캐시 본문 degrade ─────────────────────────────────

def test_stage_io_and_body_cache(tmp_path):
    run_id = "20260827-0000"
    records = [
        norm(id="a", title="포스코퓨처엠 실적", description="포스코퓨처엠 3분기 실적",
             track="posco", category="futurem", posco_relevance="primary",
             canonical_url="https://ex.com/a"),
        norm(id="b", title="LG엔솔 수주", description="LG에너지솔루션 유럽 수주",
             track="battery", category="cell-kr", canonical_url="https://ex.com/b"),
    ]
    common.write_jsonl(tmp_path / run_id / "normalized.jsonl", records)

    # 캐시 본문 하나 심기 (s3_fetch 산출물 흉내) → summary_source=body 로 승격
    cache = common.ROOT / "cache"
    cache.mkdir(exist_ok=True)
    body_path = cache / f"{common.sha1_hex('https://ex.com/a')}.json"
    body_path.write_text(json.dumps(
        {"body": "포스코퓨처엠은 광양 공장 증설을 완료했다. 양극재 생산능력이 늘어난다."},
        ensure_ascii=False), encoding="utf-8")
    try:
        out = s4_analyze.run(run_id, base_dir=tmp_path)
        rows = list(common.read_jsonl(tmp_path / run_id / "analyzed.jsonl"))
        assert len(rows) == 2
        a = next(r for r in rows if r["id"] == "a")
        b = next(r for r in rows if r["id"] == "b")
        assert a["summary_source"] == "body"           # 캐시 본문 사용
        assert b["summary_source"] == "description"     # 캐시 없음 → degrade
        # 멱등성
        assert s4_analyze.run(run_id, base_dir=tmp_path).get("skipped") is True
    finally:
        body_path.unlink(missing_ok=True)
