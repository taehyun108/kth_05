"""P1 (수집·정규화) 검증 — ROADMAP.md P1 완료 기준.

완료 기준:
  1. 4트랙 수집 → dedup → 상한 컷이 동작
  2. 대표 기사·포스코 언급 기사가 상한에서 면제됨
  3. posco_relevance 나열 패턴 예외("국내 3사와 포스코퓨처엠 등")가 none 으로 강등됨

추가로 P1 필수 계약을 검증한다:
  - 기사 id = 날짜 + sha1(canonical_url)[:10]
  - posco_relevance 는 결정론 규칙, 판정 실패 시 None (fail-closed)
  - 스테이지 간 통신은 파일로만 (collected.jsonl → normalized.jsonl)
  - track_lang: posco/battery=ko, policy/trade=ko+en
"""
from __future__ import annotations

import pathlib
import sys
from datetime import timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.stages import common, s1_collect, s2_normalize  # noqa: E402
from pipeline.stages.relevance import posco_relevance  # noqa: E402

KW = common.load_keywords()
NOW = common.now_kst()


def rec(**kw):
    """collected 레코드 기본값."""
    base = {
        "title": "제목",
        "url": "https://example.com/news/1",
        "outlet": None,
        "published_at": (NOW - timedelta(hours=1)).isoformat(),
        "description": "",
        "source": "google",
        "source_type": "news",
        "lang": "ko",
        "track": "battery",
        "category": "mat-kr",
    }
    base.update(kw)
    return base


# ── 기본 계약 ─────────────────────────────────────────────────────────────

def test_article_id_format_and_canonical_stability():
    """id = 날짜 + sha1(canonical)[:10]; utm·fragment 차이는 같은 id 로 수렴."""
    u1 = "https://n.news.com/a?utm_source=x&sid=9#frag"
    u2 = "https://N.News.com/a"  # 대문자 호스트 + 트래킹 없음
    c1, c2 = common.canonical_url(u1), common.canonical_url(u2)
    assert c1 == c2 == "https://n.news.com/a"
    aid = common.make_article_id(c1, "2026-08-27")
    assert aid.startswith("2026-08-27-")
    assert len(aid.split("-")[-1]) == 10
    assert common.make_article_id(c1, "2026-08-27") == common.make_article_id(c2, "2026-08-27")


def test_posco_relevance_is_deterministic_and_fail_closed():
    # primary: 제목에 계열사명
    assert posco_relevance("포스코퓨처엠, 양극재 증설", "", KW) == "primary"
    # mention: 본문 1회, 제목엔 없음, 나열 아님
    assert posco_relevance("삼성SDI 공급망 재편", "삼성SDI가 포스코퓨처엠으로부터 양극재를 공급받는다", KW) == "mention"
    # none: 미등장
    assert posco_relevance("LG엔솔 수주", "유럽 완성차와 계약", KW) == "none"
    # fail-closed: 잘못된 입력(keywords=None) → None
    assert posco_relevance("포스코", "x", None) is None


def test_track_lang_rule():
    """T1/T2 한국어만, T3/T4 영문 포함."""
    plan = s1_collect.build_plan(KW)
    langs = {}
    for p in plan:
        langs.setdefault(p["track"], set()).add(p["lang"])
    assert langs["posco"] == {"ko"}
    assert langs["battery"] == {"ko"}
    assert langs["policy"] == {"ko", "en"}
    assert langs["trade"] == {"ko", "en"}


# ── 완료 기준 1: 4트랙 수집 → dedup → 상한 컷 ──────────────────────────────

def test_four_tracks_dedup_and_cap():
    collected = []
    # 4개 트랙 각 1건 (수집 커버리지)
    collected.append(rec(track="posco", category="futurem", title="포스코퓨처엠 실적",
                         url="https://a.com/p1"))
    collected.append(rec(track="policy", category="pol-us", lang="en",
                         title="US 45X anode rule", url="https://a.com/pol1", outlet="Federal Register"))
    collected.append(rec(track="trade", category="trade-tariff",
                         title="캐나다 관세 부과", url="https://a.com/tr1"))

    # dedup L1: 동일 canonical (utm 차이) 2건
    collected.append(rec(track="battery", category="cell-kr", title="LG엔솔 유럽 수주",
                         url="https://b.com/x?utm_source=naver", source="naver"))
    collected.append(rec(track="battery", category="cell-kr", title="LG엔솔 유럽 수주",
                         url="https://b.com/x", source="google"))
    # dedup L2: 제목 거의 동일, url 다름
    collected.append(rec(track="battery", category="cell-kr",
                         title="삼성SDI 전고체 파일럿 가동 개시", url="https://c.com/1", outlet="연합뉴스"))
    collected.append(rec(track="battery", category="cell-kr",
                         title="삼성SDI 전고체 파일럿 가동 개시", url="https://d.com/2", outlet="이데일리"))

    # 상한 초과: battery mat-kr cap=12, 비면제 13건 → 1건 컷
    for i in range(13):
        collected.append(rec(track="battery", category="mat-kr",
                             title=f"에코프로비엠 증설 계획 발표 {i:02d}",
                             url=f"https://e.com/mat/{i}", outlet="한국경제"))

    res = s2_normalize.normalize(collected, KW, now=NOW)
    c = res["meta"]["counts"]

    # dedup 동작
    assert c["after_dedup_l1"] < c["after_negative"]      # L1 병합
    assert c["after_dedup_l2"] < c["after_dedup_l1"]      # L2 병합
    # 상한 컷 동작
    assert c["dropped_by_cap"] >= 1
    mat = [a for a in res["articles"] if a["category"] == "mat-kr"]
    assert len(mat) == 12                                  # cap 정확히 적용
    # 4트랙 모두 존재
    assert set(c["by_track"]) >= {"posco", "battery", "policy", "trade"}

    # dedup 대표에 sources/dup_count 반영
    dedup_l1 = next(a for a in res["articles"] if a["title"] == "LG엔솔 유럽 수주")
    assert set(dedup_l1["sources"]) == {"naver", "google"}
    dedup_l2 = next(a for a in res["articles"] if a["title"].startswith("삼성SDI 전고체"))
    assert dedup_l2["dup_count"] >= 1
    assert dedup_l2["outlet"] == "연합뉴스"                 # 통신사 대표 선정


# ── 완료 기준 2: 대표·포스코 언급 기사 상한 면제 ──────────────────────────

def test_cap_exemption_for_posco_and_representative():
    collected = []
    # 비면제 필러 13건 (cap 12 초과) — 낮지 않은 prescore
    for i in range(13):
        collected.append(rec(track="battery", category="mat-kr",
                             title=f"엘앤에프 양극재 공급 계약 {i:02d}",
                             url=f"https://f.com/{i}", outlet="한국경제"))
    # 포스코 언급 + 매우 낮은 prescore (무명 매체, 최근성 없음) → 그래도 면제로 생존
    collected.append(rec(track="battery", category="mat-kr",
                         title="소재업계 동향 스케치",
                         description="현장에서 포스코퓨처엠 관계자를 만났다",
                         url="https://g.com/posco", outlet="무명매체",
                         published_at=(NOW - timedelta(days=5)).isoformat()))
    # 전재 대표(멀티소스) + 낮은 prescore → 면제로 생존
    collected.append(rec(track="battery", category="mat-kr", title="배터리 소재 수급 점검 리포트",
                         url="https://h.com/wire?utm_source=naver", source="naver", outlet="무명매체",
                         published_at=(NOW - timedelta(days=5)).isoformat()))
    collected.append(rec(track="battery", category="mat-kr", title="배터리 소재 수급 점검 리포트",
                         url="https://h.com/wire", source="google", outlet="무명매체",
                         published_at=(NOW - timedelta(days=5)).isoformat()))

    res = s2_normalize.normalize(collected, KW, now=NOW)
    mat = {a["id"]: a for a in res["articles"] if a["category"] == "mat-kr"}

    posco_art = next(a for a in mat.values() if a["title"] == "소재업계 동향 스케치")
    wire_art = next(a for a in mat.values() if a["title"].startswith("배터리 소재 수급"))

    # 면제 대상이므로 컷에서 살아남았다
    assert posco_art["cap_exempt"] is True
    assert posco_art["posco_relevance"] in ("primary", "mention")
    assert wire_art["cap_exempt"] is True
    assert len(wire_art["sources"]) > 1
    # 비면제 필러는 cap 12 로 컷 (13 → 12)
    fillers = [a for a in mat.values() if a["title"].startswith("엘앤에프")]
    assert len(fillers) == 12
    assert res["meta"]["counts"]["dropped_by_cap"] >= 1


# ── 완료 기준 3: 나열 패턴 → none 강등 ────────────────────────────────────

def test_enumeration_demoted_to_none():
    # "국내 배터리 3사와 포스코퓨처엠 등" — 포스코가 있어도 none
    r = posco_relevance("국내 배터리사 실적 일제히 개선",
                        "LG엔솔·삼성SDI·SK온 국내 배터리 3사와 포스코퓨처엠 등이 호실적을 냈다", KW)
    assert r == "none"

    # 시세·종목 리스트 언급도 none
    r2 = posco_relevance("오늘의 증시", "종목 시세 표: 포스코퓨처엠 350,000 삼성SDI 400,000", KW)
    assert r2 == "none"

    # 대비: 제목에 계열사명이 있으면 나열 강등 대상 아님 (primary 유지)
    r3 = posco_relevance("포스코퓨처엠 등 소재 3사 컨퍼런스콜",
                        "포스코퓨처엠 등 소재 3사가 참석했다", KW)
    assert r3 == "primary"


# ── 스테이지 간 파일 통신 (end-to-end) ────────────────────────────────────

def test_stage_io_via_files(tmp_path):
    run_id = "20260827-0000"
    collected = [
        rec(track="posco", category="futurem", title="포스코퓨처엠 양극재 증설", url="https://a.com/1"),
        rec(track="battery", category="cell-kr", title="LG엔솔 수주", url="https://a.com/2"),
    ]
    common.write_jsonl(tmp_path / run_id / "collected.jsonl", collected)

    out = s2_normalize.run(run_id, base_dir=tmp_path)
    assert (tmp_path / run_id / "normalized.jsonl").exists()
    rows = list(common.read_jsonl(tmp_path / run_id / "normalized.jsonl"))
    assert len(rows) == 2
    # 멱등성: 재실행 시 스킵
    out2 = s2_normalize.run(run_id, base_dir=tmp_path)
    assert out2.get("skipped") is True

    # L1/L2 필드는 정규화 산출물에 없다 (INV-6, 하류에서 optional)
    assert all("summary" not in r and "tone" not in r and "swot_axis" not in r for r in rows)
    # posco 기사 게이트 판정 존재
    posco = next(r for r in rows if r["track"] == "posco")
    assert posco["posco_relevance"] == "primary"
