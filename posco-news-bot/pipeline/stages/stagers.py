"""stagers — 정책·분쟁 단계 판정(L0 규칙) + 엔티티 관리 (docs/01·04·10).

정책·분쟁을 ★엔티티★로 두고, 기사는 그 엔티티의 상태 변화 이벤트(timeline)로 붙는다.
단계 판정은 결정론 규칙이며 ★원문 소스 타입을 강한 신호로 사용★한다:
  - Federal Register 'Proposed Rule', 관보 '입법예고/행정예고/공포/시행' → 거의 100% 정확
  - 뉴스 단독 기사(강한 신호 없음) → policy는 discussion, dispute는 initiated 기본값 (P1-2·P1-9)

L2 필드(our_position·policy_ask)는 이 판정과 무관하며, board 축약본(L1)에서 제거된다.
"""
from __future__ import annotations

import re
from typing import Any

from . import common

_NON_WORD = re.compile(r"[^0-9A-Za-z가-힣]+")

# 정책 단계 규칙 (강한 신호 우선). '예고/공고'가 선제 대응 단계라 가장 먼저 본다.
POLICY_RULES: list[tuple[str, list[str]]] = [
    ("proposed",  ["입법예고", "행정예고", "규제예고", "개정안 공고", "proposed rule", "의견수렴", "공고"]),
    ("enacted",   ["공포", "제정", "의결", "가결", "final rule", "확정"]),
    ("effective", ["시행", "발효"]),
    ("amended",   ["개정", "폐지", "일부개정"]),
]

# 분쟁 단계 규칙
DISPUTE_RULES: list[tuple[str, list[str]]] = [
    ("preliminary", ["예비판정", "잠정관세", "preliminary determination"]),
    ("final",       ["최종판정", "확정판정", "final determination"]),
    ("in_force",    ["발효", "관세 부과", "관세 시행", "in force"]),
    ("negotiating", ["협상", "유예", "면제 협상", "합의"]),
    ("terminated",  ["종료", "철회", "해제", "기각"]),
    ("initiated",   ["제소", "조사개시", "조사 착수", "301조 조사", "반덤핑 조사", "세이프가드 조사"]),
]

STRONG_SOURCES = {"gazette", "press_release"}


def _match(text: str, rules: list[tuple[str, list[str]]]) -> str | None:
    low = (text or "").lower()
    for stage, kws in rules:
        if any(k.lower() in low for k in kws):
            return stage
    return None


def classify_policy_stage(text: str, source_type: str | None = None) -> str:
    """정책 단계. 강한 신호(키워드) 없으면 discussion(뉴스 단독 기본값)."""
    return _match(text, POLICY_RULES) or "discussion"


def classify_dispute_stage(text: str, source_type: str | None = None) -> str:
    """분쟁 단계. 강한 신호 없으면 initiated(뉴스 단독 기본값)."""
    return _match(text, DISPUTE_RULES) or "initiated"


def stage_confidence(text: str, source_type: str | None, rules: list[tuple[str, list[str]]]) -> str:
    """관보·보도자료(원문)거나 명시적 키워드가 있으면 high, 아니면 low."""
    if source_type in STRONG_SOURCES:
        return "high"
    return "high" if _match(text, rules) else "low"


# ── affects_futurem (퓨처엠 취급 품목·원료) ─────────────────────────────────

def futurem_materials(keywords: dict[str, Any] | None = None) -> list[str]:
    kw = keywords or common.load_keywords()
    return list(kw.get("futurem_products") or [])


def affects_futurem(text: str, keywords: dict[str, Any] | None = None) -> bool:
    low = (text or "").lower()
    return any(m.lower() in low for m in futurem_materials(keywords))


def matched_materials(text: str, keywords: dict[str, Any] | None = None) -> list[str]:
    low = (text or "").lower()
    return [m for m in futurem_materials(keywords) if m.lower() in low]


# ── 엔티티 관리: 기사 → 타임라인 이벤트 (중복 없음) ─────────────────────────

def _slug(text: str) -> str:
    return (_NON_WORD.sub("-", (text or "").lower()).strip("-") or "x")[:24]


def _article_text(a: dict[str, Any]) -> str:
    return f"{a.get('title','')} {a.get('summary','')} {a.get('description','')}"


def _first(seq: list[Any] | None, default: str) -> str:
    return seq[0] if seq else default


def build_policies(articles: list[dict[str, Any]], existing: list[dict[str, Any]] | None = None,
                   keywords: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """정책 트랙 기사를 정책 엔티티로 묶고 타임라인을 쌓는다. 같은 기사는 중복 편입 안 함."""
    kw = keywords or common.load_keywords()
    policies: dict[str, dict[str, Any]] = {p["policy_id"]: p for p in (existing or [])}
    seen: dict[str, set[str]] = {
        pid: {aid for ev in p.get("timeline", []) for aid in ev.get("article_ids", [])}
        for pid, p in policies.items()
    }

    for a in articles:
        if a.get("track") != "policy":
            continue
        country = _first(a.get("countries"), "KR")
        issue = _first(a.get("topics"), a.get("category") or "policy")
        pid = f"{country.lower()}-{_slug(issue)}"
        p = policies.get(pid)
        if p is None:
            p = {
                "policy_id": pid, "country": country, "name": issue,
                "issue_tags": [issue], "current_stage": "discussion",
                "affects_futurem": False, "affects": [],
                "timeline": [], "our_position": None, "policy_ask": None,
                "linked_issue_id": None, "last_updated": None,
            }
            policies[pid] = p
            seen[pid] = set()
        aid = a.get("id", "")
        if aid in seen[pid]:
            continue                                   # ★타임라인 중복 방지★
        text = _article_text(a)
        stage = classify_policy_stage(text, a.get("source_type"))
        p["timeline"].append({
            "date": a.get("date"), "stage": stage, "article_ids": [aid],
            "source_type": a.get("source_type"),
            "confidence": stage_confidence(text, a.get("source_type"), POLICY_RULES),
        })
        seen[pid].add(aid)
        mats = matched_materials(text, kw)
        if mats:
            p["affects_futurem"] = True
            p["affects"] = sorted(set(p["affects"]) | set(mats))

    for p in policies.values():
        _recompute(p)
    return list(policies.values())


def build_disputes(articles: list[dict[str, Any]], existing: list[dict[str, Any]] | None = None,
                   keywords: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """통상 트랙 기사를 분쟁 엔티티(부과국×대상국)로 묶고 타임라인을 쌓는다."""
    kw = keywords or common.load_keywords()
    disputes: dict[str, dict[str, Any]] = {d["dispute_id"]: d for d in (existing or [])}
    seen: dict[str, set[str]] = {
        did: {aid for ev in d.get("timeline", []) for aid in ev.get("article_ids", [])}
        for did, d in disputes.items()
    }

    for a in articles:
        if a.get("track") != "trade":
            continue
        countries = a.get("countries") or []
        imposing = countries[0] if countries else "US"
        target = countries[1] if len(countries) > 1 else "KR"
        measure = _first(a.get("topics"), a.get("category") or "trade")
        did = f"{imposing.lower()}-{target.lower()}-{_slug(measure)}"
        d = disputes.get(did)
        if d is None:
            d = {
                "dispute_id": did, "imposing_country": imposing, "target_country": target,
                "measure_type": measure, "products": [], "affects_futurem": False,
                "current_stage": "initiated", "current_rate": None,
                "timeline": [], "linked_issue_id": None, "last_updated": None,
            }
            disputes[did] = d
            seen[did] = set()
        aid = a.get("id", "")
        if aid in seen[did]:
            continue
        text = _article_text(a)
        stage = classify_dispute_stage(text, a.get("source_type"))
        d["timeline"].append({
            "date": a.get("date"), "stage": stage, "article_ids": [aid],
            "source_type": a.get("source_type"),
            "confidence": stage_confidence(text, a.get("source_type"), DISPUTE_RULES),
        })
        seen[did].add(aid)
        mats = matched_materials(text, kw)
        if mats:
            d["affects_futurem"] = True
            d["products"] = sorted(set(d["products"]) | set(mats))

    for d in disputes.values():
        _recompute(d, stage_field="current_stage")
    return list(disputes.values())


def _recompute(entity: dict[str, Any], stage_field: str = "current_stage") -> None:
    tl = sorted(entity.get("timeline", []), key=lambda e: (e.get("date") or ""))
    entity["timeline"] = tl
    if tl:
        entity[stage_field] = tl[-1]["stage"]          # 최신 날짜 이벤트의 단계
        entity["last_updated"] = tl[-1].get("date")


# ── board 축약본 (L1 — 민감정보 제외) ───────────────────────────────────────

# board 에서 제외하는 L2 전용 필드
SENSITIVE = {"our_position", "policy_ask", "affects", "products", "affects_futurem"}


def to_board(entity: dict[str, Any]) -> dict[str, Any]:
    """L1 보드 축약본 — our_position·policy_ask·affects_futurem 등 민감 필드 제거."""
    out = {k: v for k, v in entity.items() if k not in SENSITIVE}
    # 타임라인은 날짜·단계·근거 기사만 남기고 confidence/source 는 유지(비민감)
    return out


def policy_board(policies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [to_board(p) for p in policies]


def dispute_board(disputes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [to_board(d) for d in disputes]


def pin_by_affects(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """affects_futurem=True 를 상단 고정 (L2 뷰 — 퓨처엠 취급 품목 우선)."""
    return sorted(entities, key=lambda e: (0 if e.get("affects_futurem") else 1,
                                           e.get("last_updated") or ""), reverse=False)
