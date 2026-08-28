"""s5_swot — 이슈 클러스터링 + 퓨처엠 기준 SWOT + 주간 outlook (L2 전용).

docs/03-swot-law.md. 산출은 data/issues.json·weekly.json 이며 ★웹에서만★ 노출한다(INV-3).
발송 코드는 이 파일/산출물을 import 하지 않는다.

핵심(프롬프트 튜닝의 실체는 결정론 가드다):
  - SWOT 축 배치는 규칙으로 강제한다. S/W 는 포스코퓨처엠 내부 요인만,
    경쟁사·정부·시장은 전부 O/T. 정책은 무조건 T 가 아니라 ★상대적 유불리★로 판단.
  - 이슈 id 는 최초 생성 시 확정, 재클러스터링은 기사 추가만. 병합 시 merged_into.
  - outlook.likely 는 근거 기사 id 필수. 없으면 monitoring 으로 강등(근거 없는 예측 차단).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from . import common

BASELINE = "포스코퓨처엠"  # INV-2 고정

# swot-analyst 고정 헤더 (docs §8.2) — L2 프롬프트에 그대로 삽입
SWOT_HEADER = (
    "당신은 포스코퓨처엠 대외협력 담당자입니다. 아래 기사들이 포스코퓨처엠에게 무엇을 "
    "의미하는지 분석하십시오.\n"
    "규칙:\n"
    "1. S·W는 반드시 포스코퓨처엠 내부 요인만 기술. 경쟁사·정부·시장 특성은 S·W에 쓸 수 없습니다.\n"
    "2. O·T는 외부 환경 요인만. 경쟁사의 강점은 T입니다.\n"
    "3. 규제·정책은 자동으로 T가 아닙니다. 상대적 유불리를 따지십시오. "
    "규제 강화가 중국 경쟁사에 더 불리하면 그것은 포스코퓨처엠에게 O입니다.\n"
    "4. 각 항목에 근거 기사 id를 붙이고, 근거가 없으면 evidence:[], confidence:'low'.\n"
    "5. 추측을 사실처럼 쓰지 마십시오. 모르면 항목을 비우십시오.\n"
    "6. policy_ask는 정부에 실제로 요청 가능한 구체적 조치여야 합니다."
)

CLUSTER_THRESHOLD = 0.3
_NON_WORD = re.compile(r"[^0-9A-Za-z가-힣]+")


# ── 엔티티 사전 (내부/외부 판정) ────────────────────────────────────────────

def _load_aliases(keywords: dict[str, Any] | None = None) -> tuple[list[str], list[str]]:
    kw = keywords or common.load_keywords()
    futurem = list((kw.get("posco_entities") or {}).get("futurem") or []) + [BASELINE]
    competitors: list[str] = []
    for label, aliases in (kw.get("company_aliases") or {}).items():
        competitors.append(label)
        competitors.extend(aliases)
    return futurem, competitors


# ── SWOT 축 배치 (결정론 가드) ──────────────────────────────────────────────

def classify_axis(internal: bool, favorable: bool) -> str:
    """내부/외부 × 유불리 → S/W/O/T. 이 4분 규칙이 최빈 오류를 막는다."""
    if internal:
        return "S" if favorable else "W"   # 내부: 유리=S, 불리=W
    return "O" if favorable else "T"       # 외부: 유리=O, 불리=T (경쟁사 강점=T)


def is_internal(subject: str, futurem_aliases: list[str]) -> bool:
    """finding 의 주어가 포스코퓨처엠(내부)인가."""
    return any(a in (subject or "") for a in futurem_aliases)


def place_finding(finding: dict[str, Any], futurem_aliases: list[str]) -> str:
    """finding {subject, favorable} → 올바른 축. favorable 은 '퓨처엠에게 유리한가'."""
    return classify_axis(is_internal(finding.get("subject", ""), futurem_aliases),
                         bool(finding.get("favorable")))


def enforce_axes(issue: dict[str, Any], keywords: dict[str, Any] | None = None) -> dict[str, Any]:
    """issue['findings'] 를 규칙대로 재배치해 issue['swot'] 를 (재)생성.

    L2가 축을 잘못 넣어도 여기서 교정된다 — 경쟁사 강점이 S로 새지 않는다.
    """
    futurem, _ = _load_aliases(keywords)
    swot: dict[str, list[dict[str, Any]]] = {"S": [], "W": [], "O": [], "T": []}
    for f in issue.get("findings", []):
        ax = place_finding(f, futurem)
        swot[ax].append({
            "text": f.get("text", ""),
            "evidence": f.get("evidence", []),
            "confidence": f.get("confidence", "low"),
        })
    issue["swot"] = swot
    issue["baseline"] = BASELINE
    return issue


def validate_swot(issue: dict[str, Any], keywords: dict[str, Any] | None = None) -> list[str]:
    """SWOT 배치 검증 — S/W 에 외부(경쟁사) 요인이 있으면 위반."""
    futurem, competitors = _load_aliases(keywords)
    errs: list[str] = []
    if issue.get("baseline") != BASELINE:
        errs.append("baseline≠포스코퓨처엠 (INV-2)")
    for ax in ("S", "W"):
        for item in issue.get("swot", {}).get(ax, []):
            text = item.get("text", "")
            mentions_competitor = any(c in text for c in competitors)
            mentions_futurem = any(a in text for a in futurem)
            if mentions_competitor and not mentions_futurem:
                errs.append(f"{ax}에 외부(경쟁사) 요인: {text[:24]}")
    return errs


# ── 이슈 클러스터링 (id 안정) ───────────────────────────────────────────────

def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def iso_week(date_str: str | None) -> str:
    try:
        d = datetime.fromisoformat((date_str or "").replace("Z", "+00:00"))
    except (ValueError, TypeError):
        d = common.now_kst()
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _slug(article: dict[str, Any]) -> str:
    topics = article.get("topics") or []
    base = topics[0] if topics else (article.get("category") or "issue")
    s = _NON_WORD.sub("-", str(base).lower()).strip("-")
    return s[:24] or "issue"


def _issue_signature(article: dict[str, Any]) -> list[str]:
    # 토픽·국가 facet 위주로 서명 (트랙/카테고리보다 이슈 정체성에 가깝다)
    facets = [f for f in (article.get("facets") or [])
              if f.startswith(("topic:", "country:", "company:"))]
    return sorted(facets or (article.get("facets") or []))


def cluster(articles: list[dict[str, Any]], existing: list[dict[str, Any]],
            now: datetime | None = None, threshold: float = CLUSTER_THRESHOLD) -> list[dict[str, Any]]:
    """기사들을 이슈로 묶는다. 기존 이슈 id 는 절대 바뀌지 않고 기사만 추가된다."""
    now = now or common.now_kst()
    issues = [dict(i) for i in existing]
    used_ids = {i["issue_id"] for i in issues}

    def try_place(art: dict[str, Any], pool: list[dict[str, Any]]) -> bool:
        af = set(art.get("facets") or [])
        for iss in pool:
            if iss.get("status") == "merged":
                continue
            if jaccard(af, set(iss.get("signature") or [])) >= threshold:
                if art["id"] not in iss["articles"]:
                    iss["articles"].append(art["id"])
                return True
        return False

    new_issues: list[dict[str, Any]] = []
    for art in articles:
        if try_place(art, issues):          # 기존 이슈에 우선 편입 (id 안정)
            continue
        if try_place(art, new_issues):       # 이번 라운드 신규 이슈에 편입
            continue
        # 신규 이슈 생성 — id 는 여기서 최초 확정
        base_id = f"{iso_week(art.get('date'))}-{_slug(art)}"
        iid, n = base_id, 2
        while iid in used_ids:
            iid = f"{base_id}-{n}"
            n += 1
        used_ids.add(iid)
        new_issues.append({
            "issue_id": iid,
            "title": None,                   # L2가 부여 (없으면 slug)
            "status": "open",
            "baseline": BASELINE,
            "signature": _issue_signature(art),
            "articles": [art["id"]],
            "merged_into": None,
            "created_at": now.isoformat(),
        })
    return issues + new_issues


def merge_issues(issues: list[dict[str, Any]], src_id: str, dst_id: str) -> list[dict[str, Any]]:
    """src 이슈를 dst 로 병합. src 는 status=merged + merged_into 포인터만 남긴다."""
    by_id = {i["issue_id"]: i for i in issues}
    src, dst = by_id.get(src_id), by_id.get(dst_id)
    if not src or not dst:
        raise KeyError("merge 대상 이슈 없음")
    for aid in src.get("articles", []):
        if aid not in dst["articles"]:
            dst["articles"].append(aid)
    src["status"] = "merged"
    src["merged_into"] = dst_id
    src["articles"] = []
    return issues


# ── 주간 outlook (근거 없는 예측 차단) ──────────────────────────────────────

def validate_outlook(outlook: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """likely 는 근거 기사 id 필수. 없으면 monitoring 으로 강등."""
    likely_ok: list[dict[str, Any]] = []
    monitoring = list(outlook.get("monitoring", []))
    demoted: list[str] = []
    for item in outlook.get("likely", []):
        if item.get("basis"):
            likely_ok.append(item)
        else:
            d = dict(item)
            d["confidence"] = "low"
            d["_demoted_from"] = "likely"
            monitoring.append(d)
            demoted.append(item.get("text", ""))
    out = dict(outlook)
    out["likely"] = likely_ok
    out["monitoring"] = monitoring
    return out, demoted


# ── 발행 ─────────────────────────────────────────────────────────────────────

def write_issues(issues: list[dict[str, Any]], data_dir: Path | None = None) -> Path:
    data = data_dir or (common.ROOT / "data")
    data.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "generated_at": common.now_kst().isoformat(),
        "baseline": BASELINE,           # INV-2
        "web_only": True,
        "issues": issues,
    }
    p = data / "issues.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def build_weekly(week: str, issues: list[dict[str, Any]], counts: dict[str, Any],
                 outlook: dict[str, Any]) -> dict[str, Any]:
    out, _ = validate_outlook(outlook)
    open_issues = [i for i in issues if i.get("status") == "open"]
    return {
        "schema_version": "1.0",
        "generated_at": common.now_kst().isoformat(),
        "week": week,
        "web_only": True,
        "counts": counts,
        "key_issues": [i["issue_id"] for i in open_issues[:5]],
        "outlook": out,
    }


def write_weekly(weekly: dict[str, Any], data_dir: Path | None = None) -> Path:
    data = data_dir or (common.ROOT / "data")
    data.mkdir(parents=True, exist_ok=True)
    p = data / "weekly.json"
    p.write_text(json.dumps(weekly, ensure_ascii=False, indent=2), encoding="utf-8")
    return p
