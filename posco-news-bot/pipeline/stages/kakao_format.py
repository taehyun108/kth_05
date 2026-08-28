"""카카오톡 고정 포맷 검증 (docs/06-dispatch.md §4.7.3, INV-10).

🔒 고정 명세는 코드로 강제한다. 통과 못 한 건은 발송하지 않는다(fail-closed).
이 모듈이 validate_kakao 의 유일한 소스다 — 테스트도 여기서 import 한다(중복 정의 금지).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]

# 금지 문자: 이모지·불릿·해시태그·마크다운·URL
BANNED = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]|^[•·\-└*]|#\w|\*\*|https?://")

# 머리말: [매체명] + 공백 + 본문
_HEAD = re.compile(r"^\[[^\]]{2,12}\] \S")

# 존댓말 평서문 종결 — 하십시오체는 '니다.' 로 끝난다(습니다/입니다/합니다/됩니다/갑니다…).
# 개조식·명사형('있음')과 평서형 반말('했다.','이다.')을 모두 거부한다.
_POLITE_END = re.compile(r"니다\.$")
# 반말 평서문 종결의 대표형(있어도 니다. 검사에서 이미 걸리지만, 사유를 명확히 하려 별도 확인)
_PLAIN_END = re.compile(r"(했다|한다|이다|였다|된다|밝혔다|봤다|난다|왔다|간다)\.$")


def posco_entities() -> list[str]:
    """keywords.yaml posco_entities 를 평탄화(카톡 본문 포스코 언급 검사용)."""
    kw = yaml.safe_load((ROOT / "pipeline" / "keywords.yaml").read_text(encoding="utf-8"))
    terms: list[str] = []
    for aliases in (kw.get("posco_entities") or {}).values():
        terms.extend(aliases)
    return terms


def validate_card(card: dict[str, Any]) -> list[str]:
    """메시지1 카드 4요소 검증."""
    e: list[str] = []
    for k in ("thumbnail", "title", "description", "link"):
        if not card.get(k):
            e.append(f"card.{k} 누락")
    if str(card.get("link", "")).startswith(("http://bit.ly", "https://bit.ly")):
        e.append("단축 URL")
    return e


def validate_body(body: str, entities: list[str] | None = None) -> list[str]:
    """메시지2 본문 검증 — 머리말·문체·분량·금지문자·존댓말 종결·포스코 언급.

    L1(생성 요약)이 자체 검증에 재사용한다(카드 없이 본문만).
    """
    e: list[str] = []
    ents = entities if entities is not None else posco_entities()
    body = body or ""

    if not _HEAD.match(body):
        e.append("[매체명] 머리말 형식 위반")
    if "\n" in body:
        e.append("의도적 줄바꿈")
    if not (150 <= len(body) <= 350):
        e.append(f"분량 이탈 {len(body)}자")
    if BANNED.search(body):
        e.append("금지 문자(이모지/불릿/해시태그/URL)")

    tail = body.rstrip()
    if _PLAIN_END.search(tail):
        e.append("반말 평서문 종결('~했다.' 등) — 존댓말 아님")
    elif not _POLITE_END.search(tail):
        e.append("존댓말 평서문 종결(습니다./입니다. 등) 아님")

    if not any(k in body for k in ents):
        e.append("포스코 언급 없음")
    return e


def validate_kakao(card: dict[str, Any], body: str, entities: list[str] | None = None) -> list[str]:
    """고정 포맷 위반 사유 목록. 빈 리스트면 통과. (docs §4.7.3)"""
    return validate_card(card) + validate_body(body, entities)
