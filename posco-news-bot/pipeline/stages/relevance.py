"""posco_relevance — 카카오톡 발송의 유일한 게이트 (L0 결정론 규칙).

⛔ 절대 규칙:
  - LLM 호출 금지. keywords.yaml 의 posco_entities + relevance_demote_patterns 만 사용.
  - 판정 불가(예외) 시 None 반환 → fail-closed (호출측이 발송하지 않는다).

판정 (docs/02-analyze.md §4.4.1):
  primary : 계열사명이 제목에 등장 OR 본문에서 3회 이상
  mention : 본문 1~2회, 제목엔 없음
  none    : 미등장, 또는 나열/시세 언급(강등 패턴)
"""
from __future__ import annotations

import re
from typing import Any, Optional

Relevance = Optional[str]  # "primary" | "mention" | "none" | None(fail-closed)


def _entity_terms(keywords: dict[str, Any]) -> list[str]:
    """posco_entities 의 모든 별칭을 평탄화. 긴 문자열 우선(부분매칭 과다카운트 방지)."""
    terms: list[str] = []
    for aliases in (keywords.get("posco_entities") or {}).values():
        terms.extend(aliases)
    # 중복 제거 + 길이 내림차순
    seen: set[str] = set()
    uniq = [t for t in terms if not (t in seen or seen.add(t))]
    return sorted(uniq, key=len, reverse=True)


def _count_hits(text: str, terms: list[str]) -> int:
    """텍스트 내 계열사명 등장 횟수. 한글은 대소문자 무관, 라틴은 소문자 비교."""
    if not text:
        return 0
    hay = text.lower()
    total = 0
    for term in terms:
        needle = term.lower()
        if not needle:
            continue
        total += hay.count(needle)
    return total


def _matches_demote(text: str, patterns: list[str]) -> bool:
    for pat in patterns:
        try:
            if re.search(pat, text):
                return True
        except re.error:
            # 잘못된 패턴은 무시 (게이트를 막지 않되, 나머지 규칙은 계속)
            continue
    return False


def posco_string_hit(title: str, text: str, keywords: dict[str, Any]) -> bool:
    """포스코 문자열 등장 여부 — prescore 가중 및 상한 면제에 사용."""
    terms = _entity_terms(keywords)
    return _count_hits(f"{title} {text}", terms) > 0


def posco_relevance(title: str, text: str, keywords: dict[str, Any]) -> Relevance:
    """결정론적 1차 판정. 실패 시 None(fail-closed).

    text 는 P1 단계에서는 본문이 아직 없으므로 요약 스니펫(description)을 넣는다.
    최종 판정은 S4c(P2)에서 본문으로 재확정한다.
    """
    try:
        title = title or ""
        text = text or ""
        terms = _entity_terms(keywords)
        demote_patterns = keywords.get("relevance_demote_patterns") or []

        title_hits = _count_hits(title, terms)
        body_hits = _count_hits(text, terms)
        total = title_hits + body_hits

        if total == 0:
            return "none"

        # 제목에 계열사명이 있으면 기사 주제 → primary (나열 강등 대상 아님)
        if title_hits > 0:
            return "primary"

        # 제목엔 없고 본문에만: 나열·시세 언급이면 스팸 → none 강등
        if _matches_demote(f"{title} {text}", demote_patterns):
            return "none"

        if body_hits >= 3:
            return "primary"
        return "mention"  # body_hits in {1, 2}
    except Exception:
        # 어떤 이유로든 판정 불가 → 발송 게이트는 fail-closed
        return None
