"""P6 (SWOT + 주간 브리프) 검증 — 합성 이슈 3개로 축 배치 튜닝.

완료기준:
  - 3개 케이스 정확히 배치 (경쟁사 강점→S 금지 / 정책 상대유불리 / W·T 구분)
  - 이슈 id 재클러스터링에도 안정
  - outlook.likely 근거 기사 id 필수 (없으면 monitoring 강등)
  - SWOT 이 발송 코드에 새지 않음 (grep)
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.stages import s5_swot as swot

KW = swot.common.load_keywords()


# ── 합성 이슈 3개 (프롬프트 튜닝 케이스) ─────────────────────────────────────

CASE1 = {  # ① 경쟁사 호재
    "issue_id": "2026-W35-catl-sodium", "baseline": "포스코퓨처엠",
    "findings": [
        {"subject": "CATL", "favorable": False,
         "text": "CATL이 나트륨이온 배터리 양산에 성공하며 저가 시장 주도력을 강화했습니다",
         "evidence": ["a1"], "confidence": "high"},
    ],
}
CASE2 = {  # ② 규제 강화 — 상대적 유불리
    "issue_id": "2026-W35-eu-cfb", "baseline": "포스코퓨처엠",
    "findings": [
        {"subject": "EU 탄소발자국 규제", "favorable": True,  # 중국 경쟁사에 더 불리 → 퓨처엠엔 유리
         "text": "EU 탄소발자국 공개 의무 강화는 저탄소 공정을 갖춘 포스코퓨처엠에 상대적으로 유리합니다",
         "evidence": ["a2", "a3"], "confidence": "medium"},
    ],
}
CASE3 = {  # ③ 자사 악재 — W와 T 구분
    "issue_id": "2026-W35-futurem-util", "baseline": "포스코퓨처엠",
    "findings": [
        {"subject": "포스코퓨처엠", "favorable": False,
         "text": "포스코퓨처엠 3분기 양극재 가동률이 60%대로 하락했습니다",
         "evidence": ["a4"], "confidence": "high"},
        {"subject": "전방 수요 둔화·고객사 재고조정", "favorable": False,
         "text": "고객사 재고조정 장기화로 단결정 전환 투자 회수 시점이 밀릴 수 있습니다",
         "evidence": ["a4"], "confidence": "medium"},
    ],
}


def test_case1_competitor_boon_goes_to_T_not_S():
    swot.enforce_axes(CASE1, KW)
    assert len(CASE1["swot"]["T"]) == 1                 # 경쟁사 강점 → T
    assert CASE1["swot"]["S"] == []                     # S 에 절대 안 들어감
    assert "CATL" in CASE1["swot"]["T"][0]["text"]
    assert validate_swot_ok(CASE1)


def test_case2_regulation_relative_advantage_goes_to_O():
    swot.enforce_axes(CASE2, KW)
    assert len(CASE2["swot"]["O"]) == 1                 # 상대적 유리 → O (무조건 T 아님)
    assert CASE2["swot"]["T"] == []
    # 반례: 같은 규제가 불리하면 T
    unfav = {"issue_id": "x", "baseline": "포스코퓨처엠",
             "findings": [{"subject": "EU 규제", "favorable": False, "text": "불리", "evidence": []}]}
    swot.enforce_axes(unfav, KW)
    assert len(unfav["swot"]["T"]) == 1


def test_case3_self_setback_splits_W_and_T():
    swot.enforce_axes(CASE3, KW)
    assert len(CASE3["swot"]["W"]) == 1                 # 자사 가동률 하락 → W (내부)
    assert len(CASE3["swot"]["T"]) == 1                 # 외부 수요 둔화 → T (외부)
    assert "가동률" in CASE3["swot"]["W"][0]["text"]


def validate_swot_ok(issue) -> bool:
    return swot.validate_swot(issue, KW) == []


def test_validate_catches_competitor_strength_in_S():
    """L2가 CATL 강점을 S에 잘못 넣으면 검증기가 잡아낸다."""
    bad = {
        "issue_id": "bad", "baseline": "포스코퓨처엠",
        "swot": {"S": [{"text": "CATL의 나트륨이온 양산 능력", "evidence": [], "confidence": "low"}],
                 "W": [], "O": [], "T": []},
    }
    errs = swot.validate_swot(bad, KW)
    assert any("경쟁사" in e or "외부" in e for e in errs)


def test_axis_correction_is_recorded_not_silent():
    """L2가 CATL 원가 경쟁력을 S에 넣으면 규칙이 T로 옮기고 그 사실을 기록한다."""
    issue = {
        "issue_id": "corr", "baseline": "포스코퓨처엠",
        "findings": [
            {"subject": "CATL", "favorable": False, "axis": "S",   # L2 오배치
             "text": "CATL의 원가 경쟁력이 강화됐습니다", "evidence": ["a1"], "confidence": "high"},
            {"subject": "포스코퓨처엠", "favorable": True, "axis": "S",  # L2 정배치
             "text": "포스코퓨처엠 북미 거점 보유", "evidence": ["a2"], "confidence": "high"},
        ],
    }
    swot.enforce_axes(issue, KW)
    assert len(issue["axis_corrections"]) == 1                 # 잘못된 것만 기록
    c = issue["axis_corrections"][0]
    assert c["from"] == "S" and c["to"] == "T"
    assert "CATL" in c["text"]
    assert issue["swot"]["S"][0]["text"].startswith("포스코퓨처엠")  # 정배치는 S 유지
    assert swot.count_axis_corrections([issue]) == 1


def test_baseline_fixed_to_futurem():
    wrong = {"issue_id": "x", "baseline": "포스코홀딩스", "swot": {"S": [], "W": [], "O": [], "T": []}}
    assert any("baseline" in e for e in swot.validate_swot(wrong, KW))


# ── 이슈 id 안정성 ───────────────────────────────────────────────────────────

def art(aid, topic, company, date="2026-08-27"):
    return {"id": aid, "date": date,
            "facets": [f"topic:{topic}", f"company:{company}", "track:battery"]}


def test_issue_id_stable_across_reclustering():
    a1 = art("a1", "나트륨이온", "CATL")
    a2 = art("a2", "나트륨이온", "CATL")
    round1 = swot.cluster([a1, a2], [])
    assert len(round1) == 1
    iid = round1[0]["issue_id"]
    assert set(round1[0]["articles"]) == {"a1", "a2"}

    # 재클러스터링: 유사 기사 추가 → 같은 이슈 id, 기사만 늘어남
    a3 = art("a3", "나트륨이온", "CATL")
    round2 = swot.cluster([a3], round1)
    assert len(round2) == 1                              # 신규 이슈 안 생김
    assert round2[0]["issue_id"] == iid                 # id 불변
    assert set(round2[0]["articles"]) == {"a1", "a2", "a3"}

    # 무관한 기사 → 새 이슈 (기존 id 는 그대로)
    b1 = art("b1", "흑연-수출통제", "화유코발트")
    round3 = swot.cluster([b1], round2)
    assert len(round3) == 2
    assert any(i["issue_id"] == iid for i in round3)


def test_merge_leaves_pointer():
    a1 = art("a1", "t1", "CATL")
    b1 = art("b1", "t2", "BYD")
    issues = swot.cluster([a1, b1], [])
    src, dst = issues[0]["issue_id"], issues[1]["issue_id"]
    merged = swot.merge_issues(issues, src, dst)
    s = next(i for i in merged if i["issue_id"] == src)
    d = next(i for i in merged if i["issue_id"] == dst)
    assert s["status"] == "merged" and s["merged_into"] == dst
    assert "a1" in d["articles"]


# ── outlook 근거 필수 ────────────────────────────────────────────────────────

def test_outlook_likely_requires_basis():
    outlook = {
        "likely": [
            {"text": "근거 있는 전개", "basis": ["2026-08-26-x"], "confidence": "medium"},
            {"text": "근거 없는 추측", "basis": [], "confidence": "medium"},
        ],
        "monitoring": [],
    }
    out, demoted = swot.validate_outlook(outlook)
    assert len(out["likely"]) == 1                       # 근거 있는 것만 남음
    assert out["likely"][0]["text"] == "근거 있는 전개"
    assert "근거 없는 추측" in demoted                    # 강등됨
    assert any(m.get("_demoted_from") == "likely" for m in out["monitoring"])


# ── SWOT 미발송 (INV-3 구조적 차단) ─────────────────────────────────────────

def test_dispatch_does_not_reference_swot():
    src = (ROOT / "pipeline/stages/s7_dispatch.py").read_text(encoding="utf-8").lower()
    for token in ("issues.json", "s5_swot", "swot", "policy_ask", "futurem_implication"):
        assert token not in src, f"발송 코드가 {token} 참조 — INV-3 위반"
