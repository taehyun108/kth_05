"""s7_dispatch — 발송 라우팅 + 안전장치 (docs/06-dispatch.md §F-07, §4.7.5).

🔒 INV-3/7: 이 파일은 비공개 분석 산출물을 import 하지 않는다 (CI grep 대상).
🔒 INV-4 : 각 라우트는 자기 filter 규칙에 맞는 기사만 받는다.
🔒 INV-10: 카톡은 validate_kakao 통과 건만. 깨질 바에는 미발송(fail-closed).
🔒 INV-6 : 카톡은 존댓말 포맷 충족 건만 발송. L0 추출 요약(extractive)만 있는 건은
           발송하지 않고 스킵 건수를 리포트에 남긴다. (발행 자체는 L0로 이미 됐다)

입력은 공개 기사(analyzed.jsonl)만. 대응논리·시사점은 읽지도 않는다.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from . import common
from .kakao_format import posco_entities, validate_kakao

DEFAULT_THUMBNAIL = "https://posco-news.example/assets/default-card.png"
IMPACT_RANK = {"high": 3, "mid": 2, "low": 1}


# ── 발송 어댑터 (승인 후 room_id 만 채우면 되는 인터페이스) ─────────────────

class KakaoAdapter(abc.ABC):
    """오픈채팅 API 어댑터. 승인 후 실제 구현체를 붙인다."""

    @abc.abstractmethod
    def send_card_pair(self, room_id: str, card: dict[str, Any], body: str) -> bool:
        """카드+요약 2메시지 발송. 성공 True. 실패 시 예외 없이 False."""


class DisabledKakaoAdapter(KakaoAdapter):
    """enabled:false 또는 미승인 상태 — 호출되면 안 된다(호출 시 즉시 실패)."""

    def send_card_pair(self, room_id: str, card: dict[str, Any], body: str) -> bool:
        raise RuntimeError("kakao route disabled — 발송 경로가 열려서는 안 된다")


class RecordingKakaoAdapter(KakaoAdapter):
    """테스트/섀도용 — 실제로 보내지 않고 기록만."""

    def __init__(self, fail_ids: set[str] | None = None) -> None:
        self.sent: list[tuple[str, dict[str, Any], str]] = []
        self.fail_ids = fail_ids or set()

    def send_card_pair(self, room_id: str, card: dict[str, Any], body: str) -> bool:
        if card.get("_id") in self.fail_ids:
            return False  # API 실패 시뮬레이션
        self.sent.append((room_id, card, body))
        return True


# ── 필터 매칭 (INV-4) ──────────────────────────────────────────────────────

def _match_cond(article: dict[str, Any], cond: dict[str, Any]) -> bool:
    """단일 조건 dict — 모든 키가 일치해야 True (값이 list면 membership)."""
    for key, want in cond.items():
        have = article.get(key)
        if isinstance(want, list):
            if have not in want:
                return False
        else:
            if have != want:
                return False
    return True


def match_filter(article: dict[str, Any], filt: dict[str, Any] | None) -> bool:
    """라우트 filter 평가. any_of(OR) / all_of(AND) / 평면 조건 지원."""
    if not filt:
        return False  # filter 없는 라우트는 발송 안 함 (INV-4, fail-closed)
    if "any_of" in filt:
        return any(_match_cond(article, c) for c in filt["any_of"])
    if "all_of" in filt:
        return all(_match_cond(article, c) for c in filt["all_of"])
    return _match_cond(article, filt)


# ── 카드/본문 구성 ─────────────────────────────────────────────────────────

def _first_sentence(text: str, limit: int = 40) -> str:
    s = (text or "").strip()
    for sep in ("다. ", ". ", "! ", "? "):
        i = s.find(sep)
        if i > 0:
            s = s[: i + 1]
            break
    return s[:limit]


def build_card(article: dict[str, Any]) -> dict[str, Any]:
    """메시지1 카드 4요소 — 형태는 절대 무너뜨리지 않는다(썸네일/부제 기본값)."""
    desc = article.get("subtitle") or _first_sentence(article.get("summary", ""))
    return {
        "_id": article.get("id"),
        "thumbnail": article.get("thumbnail") or DEFAULT_THUMBNAIL,
        "title": article.get("title", ""),
        "description": desc,
        "link": article.get("url", ""),
    }


def kakao_body(article: dict[str, Any]) -> str | None:
    """메시지2 본문 — L1/L2가 만든 존댓말 요약(kakao_summary). 없으면 None."""
    return article.get("kakao_summary")


# ── 발송 계획 (게이트·가드·상한) ───────────────────────────────────────────

@dataclass
class DispatchPlan:
    route_id: str
    to_send: list[tuple[dict[str, Any], str, dict[str, Any]]] = field(default_factory=list)  # (card, body, article)
    held: list[tuple[str, str]] = field(default_factory=list)          # (id, 사유) — 사람 승인 대기
    excluded: list[tuple[str, list[str]]] = field(default_factory=list)  # (id, 위반사유들)
    l0_skipped: list[str] = field(default_factory=list)                 # extractive-only (INV-6)
    deduped: list[str] = field(default_factory=list)                    # 이미 발송
    overflow_dropped: list[str] = field(default_factory=list)           # 상한 초과
    anomalies: list[str] = field(default_factory=list)                  # 이상 감지

    def counts(self) -> dict[str, int]:
        return {
            "to_send": len(self.to_send), "held": len(self.held),
            "excluded": len(self.excluded), "l0_skipped": len(self.l0_skipped),
            "deduped": len(self.deduped), "overflow_dropped": len(self.overflow_dropped),
        }


def _select_key(article: dict[str, Any]) -> tuple:
    # 선정 순서: impact → primary 우선 → prescore (docs §4.7.3)
    return (
        IMPACT_RANK.get(article.get("impact"), 0),
        1 if article.get("posco_relevance") == "primary" else 0,
        article.get("prescore", 0.0),
    )


def plan_kakao(
    articles: Iterable[dict[str, Any]],
    route: dict[str, Any],
    *,
    already_sent: set[str] | None = None,
    entities: list[str] | None = None,
    baseline_volume: float | None = None,
) -> DispatchPlan:
    """카톡 라우트 발송 계획. 실제 발송은 하지 않는다(순수)."""
    already_sent = already_sent or set()
    ents = entities if entities is not None else posco_entities()
    guards = route.get("guards") or {}
    plan = DispatchPlan(route_id=route["id"])

    candidates: list[dict[str, Any]] = []
    for a in articles:
        if not match_filter(a, route.get("filter")):
            continue  # 다른 라우트 소관 (INV-4)
        aid = a.get("id", "")

        # require_relevance: 판정 실패(None) 제외 — fail-closed
        if guards.get("require_relevance") and a.get("posco_relevance") in (None, "none"):
            plan.excluded.append((aid, ["posco_relevance 판정 실패/none"]))
            continue
        # 중복 발송 방지
        if aid in already_sent:
            plan.deduped.append(aid)
            continue
        # crisis 자동 발송 금지 → 보류(사람 승인)
        if guards.get("hold_on_crisis") and a.get("tone") == "crisis":
            plan.held.append((aid, "tone=crisis — 사람 승인 필요"))
            continue
        # INV-6: L0 추출 요약만 있는 건은 카톡 스킵(발행은 이미 L0로 됨)
        if a.get("summary_method") == "extractive":
            plan.l0_skipped.append(aid)
            continue
        candidates.append(a)

    # 포맷 검증 + 요약 길이 가드
    lo, hi = (guards.get("summary_len") or [150, 350])
    packed: list[dict[str, Any]] = []
    for a in candidates:
        aid = a.get("id", "")
        body = kakao_body(a)
        if not body:
            plan.excluded.append((aid, ["kakao_summary 없음(생성요약 미완)"]))
            continue
        reasons: list[str] = []
        if not (lo <= len(body) <= hi):
            reasons.append(f"요약 길이 이상 {len(body)}자")
        card = build_card(a)
        reasons += validate_kakao(card, body, entities=ents)
        if reasons:
            plan.excluded.append((aid, reasons))  # 해당 건만 제외 — 나머지는 계속
            continue
        packed.append(a)

    # 발송량 이상 감지
    if guards.get("min_volume") is not None and len(packed) < guards["min_volume"]:
        plan.anomalies.append(f"발송량 미달 {len(packed)} < {guards['min_volume']}")
    if baseline_volume and guards.get("max_volume_ratio"):
        if len(packed) > baseline_volume * guards["max_volume_ratio"]:
            plan.anomalies.append(f"발송량 급증 {len(packed)} (평소 {baseline_volume})")

    # 일일 상한 → 초과분 drop (목록형 축약 금지, INV-10)
    packed.sort(key=_select_key, reverse=True)
    limit = route.get("daily_limit")
    if limit is not None and len(packed) > limit:
        for a in packed[limit:]:
            plan.overflow_dropped.append(a.get("id", ""))
        packed = packed[:limit]

    for a in packed:
        plan.to_send.append((build_card(a), kakao_body(a), a))
    return plan


# ── 실제 발송 (킬 스위치·재시도) ───────────────────────────────────────────

@dataclass
class DispatchReport:
    route_id: str
    enabled: bool
    sent: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    plan_counts: dict[str, int] = field(default_factory=dict)
    held: list[tuple[str, str]] = field(default_factory=list)
    excluded: list[tuple[str, list[str]]] = field(default_factory=list)
    l0_skipped: list[str] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)

    def summary_line(self) -> str:
        return (f"[{self.route_id}] 발송 {len(self.sent)} · 보류 {len(self.held)} · "
                f"제외 {len(self.excluded)} · L0스킵 {len(self.l0_skipped)} · "
                f"실패 {len(self.failed)}" + (" · [DISABLED]" if not self.enabled else ""))


def dispatch_kakao(
    plan: DispatchPlan,
    route: dict[str, Any],
    adapter: KakaoAdapter,
    room_id: str = "",
    *,
    max_retries: int = 2,
) -> DispatchReport:
    """계획을 실제 발송. enabled:false 면 어댑터를 호출조차 하지 않는다(킬 스위치)."""
    rep = DispatchReport(
        route_id=plan.route_id,
        enabled=bool(route.get("enabled")),
        plan_counts=plan.counts(),
        held=plan.held,
        excluded=plan.excluded,
        l0_skipped=plan.l0_skipped,
        anomalies=plan.anomalies,
    )
    if not rep.enabled:
        return rep  # ★킬 스위치 — 발송 0, 계획만 보고★

    for card, body, article in plan.to_send:
        aid = article.get("id", "")
        ok = False
        for _ in range(max_retries + 1):
            if adapter.send_card_pair(room_id, card, body):
                ok = True
                break
        (rep.sent if ok else rep.failed).append(aid)  # 실패해도 대체 발송 금지(INV-10)
    return rep


# ── 오케스트레이터 진입점 (S7) ─────────────────────────────────────────────

def _load_routes(routes_path: Path | None = None) -> list[dict[str, Any]]:
    p = routes_path or (common.ROOT / "pipeline" / "dispatch_routes.yaml")
    return yaml.safe_load(p.read_text(encoding="utf-8"))["routes"]


def run(
    run_id: str,
    base_dir: Path | None = None,
    *,
    dispatch_allowed: bool = True,
    already_sent: set[str] | None = None,
    adapter: KakaoAdapter | None = None,
    routes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """S7 — 카톡 라우트 발송. dispatch_allowed=False 면 계획만(발송 0, fail-closed 기본).

    반환: {sent, plan_counts, newly_sent, held, l0_skipped, ...} — dispatch_log 갱신용.
    """
    base = base_dir or (common.ROOT / "raw")
    src = base / run_id / "l1.jsonl"
    if not src.exists():
        src = base / run_id / "analyzed.jsonl"
    articles = list(common.read_jsonl(src)) if src.exists() else []

    routes = routes if routes is not None else _load_routes()
    kakao = next((r for r in routes if r.get("channel") == "kakao"), None)
    if kakao is None:
        return {"sent": [], "newly_sent": [], "skipped": "no_kakao_route"}

    already = set(already_sent or set())
    plan = plan_kakao(articles, kakao, already_sent=already, entities=posco_entities())

    if not dispatch_allowed:
        # dryrun/backfill/no-dispatch — 발송하지 않는다(fail-closed 기본값)
        return {
            "sent": [], "newly_sent": [], "dispatch_allowed": False,
            "would_send": [a.get("id") for _, _, a in plan.to_send],
            "plan_counts": plan.counts(), "held": plan.held, "l0_skipped": plan.l0_skipped,
        }

    room_env = kakao.get("room_id_env", "")
    room_id = __import__("os").environ.get(room_env, "") if room_env else ""
    used_adapter = adapter or (RecordingKakaoAdapter() if kakao.get("enabled") else DisabledKakaoAdapter())
    rep = dispatch_kakao(plan, kakao, used_adapter, room_id=room_id)

    return {
        "sent": rep.sent, "newly_sent": rep.sent, "failed": rep.failed,
        "enabled": rep.enabled, "dispatch_allowed": True,
        "plan_counts": plan.counts(), "held": plan.held, "l0_skipped": plan.l0_skipped,
    }
