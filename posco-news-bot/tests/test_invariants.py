"""INV 자동 검증 — CI 필수 통과. 상세는 CLAUDE.md 불변 규칙 표 참조."""
import json, re, subprocess, sys, pathlib, yaml
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# validate_kakao 는 pipeline/stages/kakao_format.py 가 유일한 소스 (중복 정의 금지)
from pipeline.stages.kakao_format import validate_kakao, posco_entities

L2_ONLY = {"body", "futurem_implication", "swot_axis", "sector_impact",
           "frame", "tone_evidence", "policy_ask_hint", "fact_check_flags"}
FORBIDDEN = ["issues.json", "analysis.json", "weekly.json",
             "swot", "policy_ask", "futurem_implication"]


def test_inv3_inv7_dispatch_has_no_swot_refs():
    """발송·메일 경로가 비공개 분석 데이터를 참조하지 않는다."""
    targets = ["pipeline/stages/s7_dispatch.py", "pipeline/stages/s7_mail.py",
               "bot/telegram_bot.js"]
    for t in targets:
        p = ROOT / t
        if not p.exists():
            continue
        src = p.read_text(encoding="utf-8").lower()
        hits = [w for w in FORBIDDEN if w in src]
        assert not hits, f"INV-3/7 위반: {t} 에서 {hits} 참조"


def test_inv4_every_route_has_filter():
    """filter 없는 라우트는 무조건 발송이 되어 위험하다."""
    cfg = yaml.safe_load((ROOT / "pipeline/dispatch_routes.yaml").read_text(encoding="utf-8"))
    bad = []
    for r in cfg["routes"]:
        if r.get("filter"):
            continue
        parts = r.get("parts") or []
        if parts and all(p.get("filter") for p in parts):
            continue          # 멀티파트 라우트는 파트마다 filter 가 있으면 OK
        bad.append(r["id"])
    assert not bad, f"INV-4 위반: filter 없는 라우트 {bad}"


def test_inv5_inv8_no_data_in_public():
    """public/ 은 인증 없이 서빙된다. 데이터 JSON을 두면 안 된다."""
    pub = ROOT / "public"
    if not pub.exists():
        return
    leaks = [str(p.relative_to(ROOT)) for p in pub.rglob("*.json")]
    assert not leaks, f"INV-5/8 위반: public/ 에 데이터 파일 {leaks}"


def test_inv5_no_body_field_in_published_data():
    """원문 전문이 배포 데이터에 섞이면 저작권 문제."""
    f = ROOT / "data/articles.json"
    if not f.exists():
        return
    d = json.loads(f.read_text(encoding="utf-8"))
    leaked = {k for a in d["articles"] for k in a if k in L2_ONLY}
    assert not leaked, f"INV-5/8 위반: articles.json 에 비공개 필드 {leaked}"


# ── INV-10 카카오톡 고정 포맷 (validate_kakao 는 kakao_format.py 유일 소스) ──
GOLDEN_CARD = {
    "thumbnail": "https://example.com/thumb.jpg",
    "title": "미·캐나다 '관세전쟁' 불똥?…산업계 '촉각'",
    "description": "미·캐나다 북미 생산거점 관세 부담 가능성",
    "link": "https://www.newstomato.com/ReadNews.aspx?no=1234567",
}
GOLDEN_BODY = (
    "[뉴스토마토] 캐나다에 현지 생산 기반을 구축 중인 배터리 업계는 양국의 통상 갈등 확대 "
    "가능성을 주시하고 있습니다. 현재 LG에너지솔루션(373220)은 캐나다 온타리오주에 배터리 "
    "생산법인 '넥스트스타 에너지'를 운영 중이고, 포스코퓨처엠은 퀘백주에 GM과 함께 양극재 "
    "합작사 '얼티엄캠'을 설립하고 연산 3만톤 규모의 생산기지를 짓고 있습니다."
)


def test_inv10_golden_sample_passes():
    assert validate_kakao(GOLDEN_CARD, GOLDEN_BODY) == []


@pytest.mark.parametrize("body,reason", [
    ("🔴 [뉴스토마토] " + GOLDEN_BODY[9:], "이모지"),
    ("[뉴스토마토] 짧은 요약입니다.", "분량 미달"),
    ("뉴스토마토 " + GOLDEN_BODY[9:], "머리말 없음"),
    (GOLDEN_BODY.replace("있습니다.", "있음"), "명사형 종결"),
    (GOLDEN_BODY + " https://example.com", "URL 포함"),
    (GOLDEN_BODY.replace("포스코퓨처엠", "에코프로비엠"), "포스코 언급 없음"),
    # ★반말 평서문 종결 — L0 추출 요약의 '~했다.' 계열은 카톡 미발송★
    (GOLDEN_BODY.replace("짓고 있습니다.", "지었다."), "반말 종결 '지었다.'"),
    (GOLDEN_BODY.replace("짓고 있습니다.", "짓고 있다."), "반말 종결 '있다.'"),
    (GOLDEN_BODY.replace("짓고 있습니다.", "짓겠다고 밝혔다."), "반말 종결 '밝혔다.'"),
])
def test_inv10_rejects_format_violations(body, reason):
    assert validate_kakao(GOLDEN_CARD, body), f"{reason} 를 걸러내지 못함"


@pytest.mark.parametrize("tail", ["했다.", "지었다.", "있다.", "이다.", "밝혔다.", "된다.", "간다."])
def test_inv10_rejects_plain_declarative_endings(tail):
    """L0 추출 요약(기사 리드)은 반말 평서문으로 끝난다 — 카톡 게이트가 거부해야 한다."""
    body = GOLDEN_BODY.rsplit("짓고 있습니다.", 1)[0] + "생산기지를 " + tail
    errs = validate_kakao(GOLDEN_CARD, body)
    assert any("존댓말" in e or "반말" in e for e in errs), f"'{tail}' 종결을 거부하지 못함: {errs}"


@pytest.mark.parametrize("tail", ["짓고 있습니다.", "예정입니다.", "추진합니다.", "늘어납니다."])
def test_inv10_accepts_polite_endings(tail):
    """존댓말 평서문(니다.)만 종결 검사를 통과한다."""
    body = GOLDEN_BODY.rsplit("짓고 있습니다.", 1)[0] + tail
    errs = validate_kakao(GOLDEN_CARD, body)
    assert not any("존댓말" in e or "반말" in e for e in errs), f"'{tail}' 를 잘못 거부: {errs}"


def test_inv10_card_missing_field_rejected():
    for k in ("thumbnail", "title", "description", "link"):
        card = dict(GOLDEN_CARD)
        card[k] = ""
        assert validate_kakao(card, GOLDEN_BODY), f"card.{k} 누락을 걸러내지 못함"
