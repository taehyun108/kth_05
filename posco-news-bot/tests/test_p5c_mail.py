"""P5c (일일 브리핑 메일) 검증.

완료기준:
  - 전일 포스코 기사가 언론사별로 묶여 렌더
  - Part B 에 포스코 언급 기사가 섞이지 않음
  - tone 없는 L0-only 입력으로도 메일 정상 생성(요약본)
  - HTML/텍스트에 SWOT·policy_ask·futurem_implication 문자열 부재
  - CI grep 통과 (s7_mail 이 비공개 산출물 미참조)
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.stages import s7_mail


def art(**kw):
    base = {"id": "a1", "title": "제목", "summary": "요약 문장.", "bullets": ["요점1", "요점2"],
            "outlet": "연합뉴스", "url": "https://news/1", "track": "posco", "category": "futurem",
            "posco_relevance": "primary", "impact": "high", "date": "2026-08-27"}
    base.update(kw)
    return base


def sample(with_tone=True):
    arts = [
        art(id="p1", outlet="연합뉴스", title="퓨처엠 음극재 수주", tone="positive" if with_tone else None,
            posco_relevance="primary", issue_id="I1"),
        art(id="p2", outlet="연합뉴스", title="홀딩스 리튬 준공", category="holdings",
            tone="neutral" if with_tone else None, posco_relevance="primary"),
        art(id="p3", outlet="이데일리", title="퓨처엠 가동률 하락", tone="negative" if with_tone else None,
            posco_relevance="primary", issue_id="I1"),
        # Part B: 정책·통상 (포스코 미언급, impact mid+)
        art(id="b1", outlet="Federal Register", title="45X 음극재 적격비용 개정안 공고",
            track="policy", category="pol-us", posco_relevance="none", impact="high",
            countries=["US"], policy_stage="proposed", affects_futurem=True,
            tone="neutral" if with_tone else None),
        art(id="b2", outlet="조선비즈", title="중국 흑연 수출통제 발효", track="trade", category="trade-export",
            posco_relevance="none", impact="mid", countries=["CN"], dispute_stage="in_force",
            affects_futurem=True, tone="neutral" if with_tone else None),
        # 섞이면 안 되는 것: 포스코 미언급 + 저중요도 → 어디에도 안 감
        art(id="x1", title="저중요도 산업 기사", track="battery", posco_relevance="none", impact="low"),
    ]
    return arts


# ── Part A 언론사별 그룹핑 ──────────────────────────────────────────────────

def test_part_a_grouped_by_outlet():
    m = s7_mail.build_mail(sample(), base_url="https://posco.example")
    assert "③ 언론사별 보도 내역" in m["text"]
    # 연합뉴스 2건이 한 그룹으로 묶임
    assert "▸ 연합뉴스 (2건)" in m["text"]
    assert "▸ 이데일리 (1건)" in m["text"]
    a = s7_mail.select_part_a(sample())
    groups = dict(s7_mail.group_by_outlet(a))
    assert len(groups["연합뉴스"]) == 2


# ── Part B 에 포스코 언급 기사 안 섞임 ──────────────────────────────────────

def test_part_b_excludes_posco_mentions():
    b = s7_mail.select_part_b(sample())
    assert all(x["posco_relevance"] == "none" for x in b)
    assert {x["id"] for x in b} == {"b1", "b2"}          # 포스코 기사·저중요도 제외
    # 단계 배지·품목 표기·국가 플래그
    m = s7_mail.build_mail(sample())
    assert "[예고]" in m["text"] and "[발효]" in m["text"]
    assert "퓨처엠 취급 품목 해당" in m["text"]


# ── INV-6: tone 없는 L0-only 로도 메일 생성 ─────────────────────────────────

def test_l0_only_still_produces_mail():
    m = s7_mail.build_mail(sample(with_tone=False))
    assert m["subject"].endswith("(요약본)")             # 요약본 표기
    assert m["meta"]["tone"] is False
    assert "언론사별 보도 목록" in m["text"]
    assert "③ 언론사별 보도 내역" in m["text"]            # 목록은 여전히 렌더
    # 논조 열·매체별 대비(④)는 빠진다
    assert "② 주의 필요" not in m["text"]
    assert "④ 동일 사안" not in m["text"]
    assert m["html"]                                     # HTML 도 생성됨(메일 안 거름)


def test_media_contrast_only_with_tone_and_shared_issue():
    m = s7_mail.build_mail(sample(with_tone=True))
    # I1 이슈에 연합뉴스·이데일리 2개 매체 → ④ 생성
    assert "④ 동일 사안 매체별 대비" in m["text"]


# ── SWOT·policy_ask·futurem_implication 문자열 부재 ─────────────────────────

def test_output_has_no_l2_strings():
    m = s7_mail.build_mail(sample(), base_url="https://x")
    for token in ("swot", "policy_ask", "futurem_implication", "our_position", "sector_impact"):
        assert token not in m["text"].lower()
        assert token not in m["html"].lower()


# ── INV-9: 링크 없이도 업무 — bullets 전개 + 원문 우선 + 로그인 표기 ─────────

def test_inv9_self_contained():
    m = s7_mail.build_mail(sample(), base_url="https://posco.example")
    assert "요점1" in m["text"] and "요점2" in m["text"]   # bullets 본문 전개
    assert "🔗 원문" in m["text"]                          # 원문 링크 우선
    assert s7_mail.VERCEL_LABEL in m["text"]              # "전체보기(로그인)" 표기


# ── CI grep (INV-7): s7_mail 이 비공개 산출물 미참조 ────────────────────────

def test_inv7_mail_no_private_refs():
    src = (ROOT / "pipeline/stages/s7_mail.py").read_text(encoding="utf-8").lower()
    for token in ("issues.json", "analysis.json", "weekly.json", "swot", "policy_ask", "futurem_implication"):
        assert token not in src, f"s7_mail 이 {token} 참조 — INV-7 위반"


# ── SMTP 미설정 → 파일 발송(어댑터 인터페이스) ─────────────────────────────

def test_file_sender_when_no_smtp(tmp_path):
    m = s7_mail.build_mail(sample())
    sender = s7_mail.FileMailSender(tmp_path)
    assert sender.send(m["subject"], m["text"], m["html"], "team@x") is True
    files = list(tmp_path.glob("mail-*"))
    assert any(f.suffix == ".html" for f in files) and any(f.suffix == ".txt" for f in files)
