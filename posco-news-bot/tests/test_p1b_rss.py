"""RSS 소스 재설계 검증 (2026-09) — 매체별 포맷 편차 흡수 + 커버리지.

합성 피드로 검증하는 것:
  ① pubDate 포맷 3종(RFC822 +0900 / RFC822 GMT / ISO8601 Z) → 동일 KST ISO
  ② description 없는 피드 → 빈 문자열로 degrade, 항목은 살아남음
  ③ CDATA 로 감싼 제목 · HTML 태그 · 엔티티 → 평문
  ④ Atom 피드 폴백 · <link href=...>
  ⑤ 개별 피드 실패 fail-soft / 전 소스 실패만 중단 신호
  ⑥ 커버리지 — 매체별 건수 · 죽은 피드 의심 · RSS 미등록 매체 후보
  ⑦ 네이버 HUB 는 env 없으면 비활성
"""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from pipeline import orchestrator as orch
from pipeline.stages import common, rss, s1_collect

# ── 합성 피드: 매체마다 포맷이 다르다 ────────────────────────────────────────

# A사: 표준 RSS 2.0 · RFC822(+0900) · description 있음 · category 다중
FEED_A = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>가나일보</title>
  <item>
    <title>포스코퓨처엠, 양극재 신공장 착공</title>
    <link>https://a.example.com/news/1?utm_source=rss</link>
    <description>포스코퓨처엠이 광양에 양극재 공장을 짓는다.</description>
    <pubDate>Mon, 01 Sep 2026 09:00:00 +0900</pubDate>
    <category>산업</category><category>배터리</category>
  </item>
  <item>
    <title>프로야구 개막전 매진</title>
    <link>https://a.example.com/news/2</link>
    <description>야구장이 가득 찼다.</description>
    <pubDate>Mon, 01 Sep 2026 08:00:00 +0900</pubDate>
  </item>
</channel></rss>"""

# B사: RFC822(GMT) · ★description 태그 자체가 없음★ · CDATA 제목 · HTML 엔티티
FEED_B = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>비뉴스</title>
  <item>
    <title><![CDATA[<b>단독</b> 포스코홀딩스 리튬 증산 &quot;검토&quot;]]></title>
    <link>https://b.example.com/2026/09/01/lithium</link>
    <pubDate>Mon, 01 Sep 2026 00:00:00 GMT</pubDate>
  </item>
</channel></rss>"""

# C사: ISO8601(Z) · dc:date · content:encoded 만 있음(description 없음)
FEED_C = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><title>시데일리</title>
  <item>
    <title>EU, 배터리 탄소발자국 규제 시행</title>
    <link>https://c.example.com/eu-cbam</link>
    <content:encoded><![CDATA[<p>EU가 배터리 탄소발자국 신고를 의무화한다.</p>]]></content:encoded>
    <dc:date>2026-09-01T00:00:00Z</dc:date>
  </item>
</channel></rss>"""

# D사: Atom · <link href=...> · category term=... · 공백구분 naive 날짜
FEED_D = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>디프레스</title>
  <entry>
    <title>미국, 흑연 수출통제 관세 부과</title>
    <link href="https://d.example.com/graphite-tariff"/>
    <summary>흑연에 대한 상계관세가 부과된다.</summary>
    <updated>2026-09-01 09:00:00</updated>
    <category term="trade"/>
  </entry>
</feed>"""

FEEDS = {
    "https://a.example.com/rss": FEED_A.encode("utf-8"),
    "https://b.example.com/rss": FEED_B.encode("utf-8"),
    "https://c.example.com/rss": FEED_C.encode("utf-8"),
    "https://d.example.com/atom": FEED_D.encode("utf-8"),
}


def make_cfg(*ids: str) -> dict:
    all_src = [
        {"id": "a-ilbo", "name": "가나일보", "tier": 1, "url": "https://a.example.com/rss",
         "lang": "ko", "enabled": True},
        {"id": "b-news", "name": "비뉴스", "tier": 2, "url": "https://b.example.com/rss",
         "lang": "ko", "enabled": True},
        {"id": "c-daily", "name": "시데일리", "tier": 2, "url": "https://c.example.com/rss",
         "lang": "ko", "enabled": True},
        {"id": "d-press", "name": "디프레스", "tier": 1, "url": "https://d.example.com/atom",
         "lang": "en", "enabled": True, "source_type": "gazette"},
    ]
    srcs = [s for s in all_src if not ids or s["id"] in ids]
    return {"version": 1, "sources": srcs}


def fetcher(url: str) -> bytes:
    if url not in FEEDS:
        raise OSError(f"unreachable: {url}")
    return FEEDS[url]


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """feed_health.json 을 테스트별 tmp 로 격리."""
    monkeypatch.setenv("PNB_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("NAVER_HUB_KEY_ID", raising=False)
    monkeypatch.delenv("NAVER_HUB_KEY", raising=False)
    yield


@pytest.fixture
def keywords():
    return common.load_keywords()


# ── ① 날짜 포맷 3종 + naive → 동일 KST ISO ──────────────────────────────────

@pytest.mark.parametrize("raw", [
    "Mon, 01 Sep 2026 09:00:00 +0900",   # RFC822 오프셋
    "Mon, 01 Sep 2026 00:00:00 GMT",     # RFC822 GMT
    "2026-09-01T09:00:00+09:00",         # ISO8601 오프셋
    "2026-09-01T00:00:00Z",              # ISO8601 Z
    "2026-09-01 09:00:00",               # 공백구분 naive(=KST 가정)
])
def test_date_formats_normalize_to_kst(raw):
    assert rss.parse_date_any(raw) == "2026-09-01T09:00:00+09:00"


def test_unparsable_date_is_none_not_crash():
    # 날짜 파싱 실패는 항목을 버리는 사유가 아니다 — 하류가 수집시각으로 폴백
    assert rss.parse_date_any("어제") is None
    assert rss.parse_date_any("") is None


def test_date_formats_differ_per_feed_but_records_match():
    """세 매체가 서로 다른 포맷을 써도 하류에는 같은 모양으로 온다."""
    got = {}
    for fid in ("a-ilbo", "b-news", "c-daily"):
        cfg = make_cfg(fid)
        items = rss.fetch_source(cfg["sources"][0], fetcher)
        got[fid] = items[0]["published_at"]
    assert got["a-ilbo"] == "2026-09-01T09:00:00+09:00"
    assert got["b-news"] == "2026-09-01T09:00:00+09:00"   # GMT → KST 환산
    assert got["c-daily"] == "2026-09-01T09:00:00+09:00"  # dc:date Z → KST


# ── ② description 없는 피드 ─────────────────────────────────────────────────

def test_feed_without_description_survives():
    items = rss.fetch_source(make_cfg("b-news")["sources"][0], fetcher)
    assert len(items) == 1
    assert items[0]["description"] == ""          # 결손은 빈 문자열로 degrade
    assert items[0]["title"]                       # 제목은 살아 있다
    assert items[0]["url"].startswith("https://b.example.com/")


def test_content_encoded_is_description_fallback():
    items = rss.fetch_source(make_cfg("c-daily")["sources"][0], fetcher)
    assert "탄소발자국" in items[0]["description"]
    assert "<p>" not in items[0]["description"]


# ── ③ CDATA · HTML 태그 · 엔티티 ────────────────────────────────────────────

def test_cdata_title_is_plain_text():
    items = rss.fetch_source(make_cfg("b-news")["sources"][0], fetcher)
    title = items[0]["title"]
    assert title == '단독 포스코홀딩스 리튬 증산 "검토"'
    for bad in ("<b>", "</b>", "CDATA", "&quot;"):
        assert bad not in title


# ── ④ Atom 폴백 ─────────────────────────────────────────────────────────────

def test_atom_entry_and_link_href():
    items = rss.fetch_source(make_cfg("d-press")["sources"][0], fetcher)
    assert len(items) == 1
    assert items[0]["url"] == "https://d.example.com/graphite-tariff"
    assert items[0]["categories"] == ["trade"]
    assert items[0]["published_at"] == "2026-09-01T09:00:00+09:00"
    assert items[0]["source_type"] == "gazette"     # 소스 정의가 레코드로 전달된다


# ── ⑤ 필터: 피드 전체 → keywords.yaml 기준 ─────────────────────────────────

def test_filter_drops_unrelated_and_tags_track(keywords):
    items = rss.fetch_source(make_cfg("a-ilbo")["sources"][0], fetcher)
    kept, dropped = s1_collect.filter_rss_records(items, keywords)
    assert dropped == 1                                  # 프로야구 기사 제외
    assert len(kept) == 1
    assert kept[0]["track"] == "posco"                   # 포스코 엔티티 → posco 트랙


def test_posco_entity_alone_enters_posco_track(keywords):
    """must 키워드에 안 걸려도 posco_entities 히트면 편입 — 카톡 게이트 커버리지 보호."""
    hits = s1_collect.match_keywords("포스코홀딩스가 리튬 증산을 검토한다", keywords)
    assert ("posco", "group") in hits or any(t == "posco" for t, _ in hits)


# ── ⑥ 개별 피드 실패는 fail-soft ────────────────────────────────────────────

def test_single_feed_failure_does_not_stop_others():
    cfg = make_cfg()
    cfg["sources"].append({"id": "dead-feed", "name": "죽은매체",
                           "url": "https://dead.example.com/rss", "enabled": True})
    records, errors, counts = rss.collect_feeds(cfg, fetcher)
    assert counts["dead-feed"] == 0
    assert any(e["feed"] == "dead-feed" for e in errors)
    assert counts["a-ilbo"] == 2 and counts["d-press"] == 1     # 나머지는 정상 수집
    assert len(records) == 5


def test_all_sources_failed_is_signalled(keywords):
    """전 피드 실패 + 구글 미사용 → source_ok 0 (호출측이 중단 판단)."""
    cfg = {"version": 1, "sources": [
        {"id": "x", "name": "X", "url": "https://x.invalid/rss", "enabled": True}]}
    records, errors, cov = s1_collect.collect(
        keywords, use_rss=True, use_google=False, use_naver_hub=False, rss_cfg=cfg)
    assert records == []
    assert cov["source_tried"] == 1 and cov["source_ok"] == 0


def test_orchestrator_marks_s1_failed_when_all_sources_fail(tmp_path, monkeypatch):
    """전 소스 실패는 S1 failed. (정책은 fail-soft라 파이프라인은 계속)"""
    monkeypatch.setattr(s1_collect, "run", lambda **kw: {
        "records": [], "errors": [{"source": "rss", "reason": "unreachable"}],
        "coverage": {"source_tried": 2, "source_ok": 0, "by_source": {}, "by_outlet": {},
                     "feed_counts": {}, "dead_feeds": [], "unregistered_outlets": {}},
    })
    ctx = orch.make_context("daily", "T-1", resume=False, only=["S1"], no_dispatch=True,
                            base_dir=tmp_path / "raw", data_dir=tmp_path / "data")
    res = orch._s1_collect(ctx)
    assert res.status == "failed"
    assert "전 소스 실패" in res.note


# ── ⑦ 커버리지 — 매체별 건수 · 죽은 피드 · 미등록 매체 ─────────────────────

def test_coverage_counts_by_outlet(keywords):
    records, errors, cov = s1_collect.collect(
        keywords, use_rss=True, use_google=False, use_naver_hub=False,
        rss_cfg=make_cfg(), rss_fetcher=fetcher)
    assert cov["by_outlet"]["가나일보"] == 1        # 야구 기사는 필터에서 빠짐
    assert cov["by_outlet"]["비뉴스"] == 1
    assert cov["feed_counts"]["a-ilbo"] == 2        # 피드 원본 건수(필터 전)
    assert cov["source_ok"] == 1


def test_dead_feed_flagged_after_consecutive_zero(keywords):
    cfg = make_cfg("a-ilbo")
    cfg["sources"].append({"id": "silent", "name": "무음신문",
                           "url": "https://silent.example.com/rss", "enabled": True})

    def only_a(url: str) -> bytes:
        if url == "https://a.example.com/rss":
            return FEED_A.encode("utf-8")
        return b"<?xml version='1.0'?><rss version='2.0'><channel></channel></rss>"

    for i in range(s1_collect.DEAD_FEED_DAYS):
        _, _, cov = s1_collect.collect(keywords, use_rss=True, use_google=False,
                                       use_naver_hub=False, rss_cfg=cfg, rss_fetcher=only_a)
        if i < s1_collect.DEAD_FEED_DAYS - 1:
            assert "silent" not in cov["dead_feeds"]    # 아직 임계 미달
    assert cov["dead_feeds"] == ["silent"]
    assert "a-ilbo" not in cov["dead_feeds"]


def test_unregistered_outlet_candidates_from_google_only():
    """구글로만 잡힌 매체 = rss_sources.yaml 추가 후보."""
    records = [
        {"outlet": "가나일보", "source": "rss"},
        {"outlet": "미등록타임스", "source": "google"},
        {"outlet": "미등록타임스", "source": "google"},
        {"outlet": "가나일보", "source": "google"},     # 이미 등록된 매체는 후보 아님
    ]
    cov = s1_collect.build_coverage(records, {"a-ilbo": 1}, {"가나일보"}, {})
    assert cov["unregistered_outlets"] == {"미등록타임스": 2}
    assert cov["by_source"] == {"rss": 1, "google": 3}


def test_report_shows_coverage_lines():
    cov = {
        "by_source": {"rss": 3, "google": 1},
        "by_outlet": {"가나일보": 3, "미등록타임스": 1},
        "feed_counts": {"a-ilbo": 3, "silent": 0},
        "dead_feeds": ["silent"],
        "unregistered_outlets": {"미등록타임스": 1},
        "source_tried": 2, "source_ok": 2,
    }
    text = "\n".join(orch.coverage_lines(cov))
    assert "가나일보: 3건" in text
    assert "죽은 피드 의심" in text and "silent" in text
    assert "RSS 미등록 매체 후보" in text and "미등록타임스" in text


# ── ⑦-b 정체된 피드 (실제 전자신문 응답에서 발견한 고장 모드) ─────────────
#
# 2026-09-01 https://rss.etnews.com/06064.xml (전자>소재) 실호출 결과:
#   200 text/xml · item 50건 · 파싱 정상 — 그런데 최신 기사가 2026-06-25(68일 전).
#   건수 기반 '죽은 피드' 감시로는 영원히 안 잡힌다. 아래가 그 재현이다.

# 실제 응답의 구조를 그대로 옮긴 축약본 (channel <image> 블록 · CDATA · 단일자릿수 일자)
ETNEWS_STALE = """<?xml version="1.0" encoding="utf-8" ?>
<!-- LAST UPDATED AT 2026-06-26 06:33:03 -->
<rss version="2.0"><channel>
  <title><![CDATA[전자 - 소재 - 전자신문]]></title>
  <link>https://www.etnews.com</link>
  <pubDate>Fri, 26 Jun 2026 06:33:03 +0900</pubDate>
  <image>
    <title><![CDATA[전자 - 소재 - 전자신문]]></title>
    <url>https://img.etnews.com/2020/etnews/images/logo_et.png</url>
    <link>https://www.etnews.com</link>
    <description></description>
  </image>        <item>
    <title><![CDATA[이녹스리튬-정석케미칼, 전고체 배터리 핵심소재 개발 협력]]></title>
    <link>https://www.etnews.com/20260625000259</link>
    <description><![CDATA[황화리튬(Li\u2082S)은 차세대 전고체 배터리의 핵심 원료다.]]></description>
    <guid>20260625000259</guid>
    <pubDate>Thu, 25 Jun 2026 13:56:02 +0900</pubDate>
  </item>        <item>
    <title><![CDATA[동화일렉트로라이트, 건식 기반 음극 소재 개발 국책과제 주관사 선정]]></title>
    <link>https://www.etnews.com/20260624000084</link>
    <description><![CDATA[건식 기반 음극 전극 소재 기술 개발 국책과제 주관 기관으로 선정됐다.]]></description>
    <guid>20260624000084</guid>
    <pubDate>Wed, 24 Jun 2026 10:06:33 +0900</pubDate>
  </item>	</channel>
</rss>"""

ETNEWS_SRC = {"id": "etnews-material", "name": "전자신문", "lang": "ko",
              "url": "https://rss.etnews.com/06064.xml", "enabled": True}


def test_channel_image_block_is_not_an_item():
    """실제 전자신문 피드는 channel 안에 <image><title><link> 를 둔다.

    이걸 item 으로 오인하면 매 실행마다 가짜 기사가 1건씩 섞인다.
    """
    items = rss.parse_items(ETNEWS_STALE.encode("utf-8"), ETNEWS_SRC)
    assert len(items) == 2
    assert all("etnews.com/2026" in i["url"] for i in items)
    assert not any("logo_et.png" in (i["url"] or "") for i in items)


def test_single_digit_day_rfc822_parses():
    """전자신문 pubDate 는 일자가 한 자리다 — 'Tue, 1 Sep 2026'."""
    assert rss.parse_date_any("Tue, 1 Sep 2026 16:03:19 +0900") == "2026-09-01T16:03:19+09:00"


def test_feed_with_no_category_still_filters(keywords):
    """전자신문 피드에는 <category> 가 아예 없다 → 제목·설명만으로 걸러져야 한다.

    ★2026-09 사전 확장으로 메워진 구멍★
    이전엔 '동화일렉트로라이트, 건식 기반 음극 소재…'(퓨처엠 주력 음극재)가 탈락했다.
    must 가 '건식전극'·'실리콘음극' 뿐이라 띄어쓴 '건식 기반 음극'과 매칭되지 않아서다.
    지금은 must 에 음극재/음극소재를 넣고 공백 제거 매칭을 쓰므로 둘 다 통과한다.
    """
    items = rss.parse_items(ETNEWS_STALE.encode("utf-8"), ETNEWS_SRC)
    assert all(i["categories"] == [] for i in items)
    kept, dropped = s1_collect.filter_rss_records(items, keywords)
    assert len(kept) == 2 and dropped == 0
    assert {k["title"][:5] for k in kept} == {"이녹스리튬", "동화일렉트"}
    assert all(k["track"] == "battery" for k in kept)


# ── ⑩ 사전 확장 (2026-09) — 띄어쓰기 변형 흡수 ──────────────────────────────

@pytest.mark.parametrize("text,expect", [
    ("건식 기반 음극 소재 개발 국책과제", ("battery", "mat-kr")),      # 띄어쓴 '음극 소재'
    ("포스코퓨처엠 양극 활물질 라인 증설", ("posco", "futurem")),       # 포스코 우선
    ("LG화학 전구체 합작사 설립", ("battery", "mat-kr")),
    ("에코프로비엠 양극재 증설", ("battery", "mat-kr")),
    ("삼성 SDI 신규 라인 가동", ("battery", "cell-kr")),              # '삼성SDI' 사전 ↔ 띄어쓴 표기
])
def test_squash_matching_absorbs_spacing(keywords, text, expect):
    assert expect in s1_collect.match_keywords(text, keywords)


def test_squash_does_not_swallow_unrelated_text(keywords):
    """공백 제거가 아무거나 다 통과시키면 안 된다."""
    assert s1_collect.match_keywords("프로야구 개막전 매진", keywords) == []
    assert s1_collect.match_keywords("부산국제영화제 10월 6일 개막", keywords) == []


def test_dictionary_expansion_is_measured(keywords):
    """★확장분이 실제로 무엇을 더 잡는지 고정한다★

    scripts/measure_keywords.py 로 실호출 피드(전자신문 소재 50건)를 측정한 결과:
      확장 전 6건 통과(12%) → 확장 후 7건 통과(14%) · +1건
    아래는 그 +1건의 정체다. 사전을 되돌리면 이 테스트가 깨진다.
    """
    from scripts.measure_keywords import baseline_keywords
    text = "동화일렉트로라이트, 건식 기반 음극 소재 개발 국책과제 주관사 선정"
    assert s1_collect.match_keywords(text, baseline_keywords(keywords)) == []   # 확장 전: 탈락
    assert ("battery", "mat-kr") in s1_collect.match_keywords(text, keywords)   # 확장 후: 통과




def test_stale_feed_detected_even_though_items_are_plenty():
    """★건수는 정상인데 내용이 낡은 피드★ — 죽은 피드 감시로는 안 잡힌다."""
    items = rss.parse_items(ETNEWS_STALE.encode("utf-8"), ETNEWS_SRC)
    fresh = s1_collect.feed_freshness(items)
    now = datetime(2026, 9, 1, 16, 0, tzinfo=common.KST)
    stale = s1_collect.stale_feeds(fresh, now=now)
    assert stale == {"etnews-material": 68}

    cov = s1_collect.build_coverage(items, {"etnews-material": len(items)},
                                    {"전자신문"}, {}, fresh)
    assert cov["dead_feeds"] == []          # ← 0건이 아니라서 여기엔 안 걸린다
    assert cov["stale_feeds"]["etnews-material"] == 68
    text = "\n".join(orch.coverage_lines(cov))
    assert "정체된 피드" in text and "68일 경과" in text


def test_fresh_feed_is_not_flagged_stale():
    fresh = {"a-ilbo": common.now_kst().isoformat()}
    assert s1_collect.stale_feeds(fresh) == {}


def test_stale_threshold_is_per_feed():
    """주간 갱신 섹션 피드를 오탐하지 않도록 피드별 임계를 준다."""
    fresh = {"weekly-feed": "2026-08-12T09:00:00+09:00",      # 20일 전
             "daily-feed": "2026-08-25T09:00:00+09:00"}       # 7일 전
    now = datetime(2026, 9, 1, 9, 0, tzinfo=common.KST)
    # 기본 14일: weekly 만 걸린다
    assert set(s1_collect.stale_feeds(fresh, now=now)) == {"weekly-feed"}
    # weekly-feed 는 30일까지 정상으로 본다 → 아무것도 안 걸림
    assert s1_collect.stale_feeds(fresh, now=now, thresholds={"weekly-feed": 30}) == {}
    # daily-feed 를 3일 기준으로 조이면 걸린다
    got = s1_collect.stale_feeds(fresh, now=now, thresholds={"weekly-feed": 30, "daily-feed": 3})
    assert got == {"daily-feed": 7}


def test_stale_thresholds_read_from_sources_yaml():
    cfg = rss.load_sources()
    th = s1_collect.stale_thresholds(cfg)
    assert th, "rss_sources.yaml 에 stale_days 예시가 최소 1건 있어야 한다"
    assert all(isinstance(v, int) and v > 0 for v in th.values())


def test_report_always_shows_newest_article_date():
    """판정과 무관하게 최신 기사 날짜를 항상 싣는다 — 추세를 눈으로 보려고."""
    cov = {
        "by_source": {"rss": 2}, "by_outlet": {"가나일보": 2},
        "feed_counts": {"a-ilbo": 2}, "dead_feeds": [],
        "feed_newest": {"a-ilbo": "2026-09-01T09:00:00+09:00"},
        "feed_age_days": {"a-ilbo": 0},
        "stale_feeds": {}, "stale_thresholds": {}, "unregistered_outlets": {},
        "source_tried": 1, "source_ok": 1,
    }
    text = "\n".join(orch.coverage_lines(cov))
    assert "피드별 최신 기사:" in text
    assert "a-ilbo: 2026-09-01 (0일 전)" in text


# ── ⑪ verified 아니면 절대 안 켜진다 ───────────────────────────────────────

def test_unverified_feed_is_force_disabled(tmp_path):
    """★예외 없음★ enabled:true 로 적어도 verified 가 아니면 로더가 끈다."""
    y = tmp_path / "src.yaml"
    y.write_text(
        "version: 1\n"
        "defaults: {timeout_sec: 10, max_items: 50}\n"
        "sources:\n"
        "  - {id: guessed, name: 추정매체, tier: 1, section: x,\n"
        "     url: 'https://guess.example.com/rss', enabled: true, verified: false}\n"
        "  - {id: checked, name: 확인매체, tier: 1, section: x,\n"
        "     url: 'https://ok.example.com/rss', enabled: true, verified: true}\n",
        encoding="utf-8")
    cfg = rss.load_sources(y)
    assert [s["id"] for s in rss.enabled_sources(cfg)] == ["checked"]
    guessed = next(s for s in cfg["sources"] if s["id"] == "guessed")
    assert guessed["enabled"] is False
    assert guessed["disabled_reason"] == "unverified"
    assert rss.unverified_sources(cfg) == ["guessed"]


def test_shipped_sources_yaml_has_no_unverified_enabled():
    """실제 rss_sources.yaml 에도 '미확인인데 켜진' 피드가 없어야 한다."""
    cfg = rss.load_sources()
    assert all(s.get("verified") for s in rss.enabled_sources(cfg))
    assert rss.unverified_sources(cfg), "확인 대기 목록은 리포트에 노출된다"


# ── ⑫ 응답 검증기 — 200 은 성공을 뜻하지 않는다 ────────────────────────────

EDAILY_FALLBACK = (common.ROOT / "tests" / "fixtures" / "edaily_rss_index_fallback.html")


def test_edaily_error_fallback_is_rejected():
    """★실호출 캡처★ 200 · text/html · ?aspxerrorpath=/rss/ 로 리다이렉트."""
    src = {"id": "edaily-rss-index", "url": "https://www.edaily.co.kr/rss/"}
    resp = rss.FeedResponse(
        body=EDAILY_FALLBACK.read_bytes(),
        content_type="text/html",
        final_url="https://www.edaily.co.kr/?aspxerrorpath=/rss/",
        status=200,
    )
    with pytest.raises(rss.FeedInvalid) as exc:
        rss.validate_response(src, resp)
    assert "오류 페이지로 리다이렉트" in str(exc.value)


@pytest.mark.parametrize("resp,expect", [
    (rss.FeedResponse(b"<html><body>hi</body></html>", "text/html", "https://x.test/rss.xml"),
     "XML 아님"),
    (rss.FeedResponse(b"<html><body>hi</body></html>", "application/xml", "https://x.test/rss.xml"),
     "피드 아님"),
    (rss.FeedResponse(b"<?xml version='1.0'?><rss version='2.0'><channel></channel></rss>",
                      "text/xml", "https://x.test/rss.xml"),
     "item/entry 0건"),
    (rss.FeedResponse(b"<?xml version='1.0'?><rss><channel>", "text/xml", "https://x.test/rss.xml"),
     "XML 파싱 실패"),
    (rss.FeedResponse(b"<rss/>", "text/xml", "https://other.test/rss.xml"),
     "다른 주소로 리다이렉트"),
])
def test_response_validator_rejects(resp, expect):
    with pytest.raises(rss.FeedInvalid) as exc:
        rss.validate_response({"id": "x", "url": "https://x.test/rss.xml"}, resp)
    assert expect in str(exc.value)


def test_response_validator_accepts_real_feed_shapes():
    src = {"id": "a-ilbo", "url": "https://a.example.com/rss"}
    # 표준 RSS · Atom · Content-Type 미제공 · www 유무 차이 → 모두 통과
    for body, ctype, final in [
        (FEED_A.encode("utf-8"), "text/xml; charset=utf-8", "https://a.example.com/rss"),
        (FEED_D.encode("utf-8"), "application/atom+xml", "https://a.example.com/rss"),
        (FEED_A.encode("utf-8"), "", "https://a.example.com/rss"),
        (FEED_A.encode("utf-8"), "text/xml", "https://www.a.example.com/rss"),
    ]:
        rss.validate_response(src, rss.FeedResponse(body, ctype, final))


def test_invalid_response_is_recorded_as_collect_failure():
    """검증 실패는 fail-soft 로 넘기되 ★수집 실패로 기록★된다."""
    cfg = {"version": 1, "sources": [
        {"id": "bad", "name": "오류매체", "url": "https://bad.test/rss/", "enabled": True},
        {"id": "a-ilbo", "name": "가나일보", "url": "https://a.example.com/rss", "enabled": True}]}

    def f(url):
        if url == "https://bad.test/rss/":
            return rss.FeedResponse(b"<html>x</html>", "text/html",
                                    "https://bad.test/?aspxerrorpath=/rss/")
        return rss.FeedResponse(FEED_A.encode("utf-8"), "text/xml", url)

    records, errors, counts = rss.collect_feeds(cfg, f)
    assert counts["bad"] == 0 and counts["a-ilbo"] == 2      # 정상 피드는 계속 수집
    bad = next(e for e in errors if e["feed"] == "bad")
    assert bad["kind"] == "invalid_response" and bad["level"] == "error"
    assert "오류 페이지로 리다이렉트" in bad["reason"]


def test_report_shows_invalid_reason_and_pending():
    cov = {
        "by_source": {"rss": 2}, "by_outlet": {"가나일보": 2}, "feed_counts": {"bad": 0},
        "dead_feeds": [], "feed_newest": {}, "feed_age_days": {},
        "stale_feeds": {}, "stale_thresholds": {}, "unregistered_outlets": {},
        "invalid_feeds": {"bad": "오류 페이지로 리다이렉트 (https://bad.test/?aspxerrorpath=/rss/)"},
        "pending_feeds": ["yonhap-economy", "etnews-parts"],
        "source_tried": 1, "source_ok": 1,
    }
    text = "\n".join(orch.coverage_lines(cov))
    assert "응답 검증 실패" in text and "오류 페이지로 리다이렉트" in text
    assert "확인 대기" in text and "yonhap-economy" in text


# ── ⑬ 카테고리 필터 (이데일리처럼 <category> 를 주는 피드) ──────────────────

EDAILY_FEED = """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0"><channel>
<title>이데일리 - 전체뉴스</title>
<item>
	<title><![CDATA[공정위, 장류 담합 현장조사]]></title>
	<link>https://www.edaily.co.kr/News/Read?newsId=1</link>
	<category>산업/통상</category>
	<pubDate>Tue, 01 Sep 2026 16:20:39 +0900</pubDate>
</item>
<item>
	<title><![CDATA[[포토] 부산국제영화제 10월 6일 개막]]></title>
	<link>https://www.edaily.co.kr/News/Read?newsId=2</link>
	<category>영화계소식</category>
	<pubDate>Tue, 01 Sep 2026 16:32:09 +0900</pubDate>
</item>
<item>
	<title><![CDATA[차명석 LG 단장 백의종군]]></title>
	<link>https://www.edaily.co.kr/News/Read?newsId=3</link>
	<category>국내야구소식</category>
	<pubDate>Tue, 01 Sep 2026 16:31:22 +0900</pubDate>
</item>
<item>
	<title><![CDATA[LGD, 차세대 OLED 인재 확보]]></title>
	<link>https://www.edaily.co.kr/News/Read?newsId=4</link>
	<category>전자</category>
	<pubDate>Tue, 01 Sep 2026 16:33:13 +0900</pubDate>
</item>
<item>
	<title><![CDATA[카테고리 없는 기사]]></title>
	<link>https://www.edaily.co.kr/News/Read?newsId=5</link>
	<pubDate>Tue, 01 Sep 2026 16:00:00 +0900</pubDate>
</item>
</channel></rss>"""


def test_category_filter_narrows_firehose():
    cfg = {"version": 1, "sources": [{
        "id": "edaily-all", "name": "이데일리", "url": "https://e.test/rss.xml",
        "enabled": True, "category_filter": ["산업", "전자"]}]}
    records, errors, counts = rss.collect_feeds(
        cfg, lambda u: rss.FeedResponse(EDAILY_FEED.encode("utf-8"), "text/xml", u))
    titles = [r["title"][:6] for r in records]
    assert "공정위, 장류" in " ".join(titles) or any("공정위" in t for t in titles)
    assert not any("부산국제" in r["title"] for r in records)     # 영화 제외
    assert not any("차명석" in r["title"] for r in records)       # 야구 제외
    assert counts["edaily-all"] == 3        # 산업/통상 · 전자 · 카테고리 없는 1건
    assert any(e.get("reason", "").startswith("category_filter") for e in errors)


def test_category_filter_keeps_uncategorized_items():
    """분류 누락으로 기사를 잃지 않는다 — category 가 빈 항목은 통과시킨다."""
    src = {"category_filter": ["산업"]}
    assert rss.category_allows(src, {"categories": []}) is True
    assert rss.category_allows(src, {"categories": ["산업/통상"]}) is True
    assert rss.category_allows(src, {"categories": ["영화계소식"]}) is False
    assert rss.category_allows({}, {"categories": ["영화계소식"]}) is True   # 필터 미설정


def test_category_then_keyword_two_stage(keywords):
    """2단 구조: 카테고리로 줄인 뒤 키워드로 거른다."""
    cfg = {"version": 1, "sources": [{
        "id": "edaily-all", "name": "이데일리", "url": "https://e.test/rss.xml",
        "enabled": True, "category_filter": ["산업", "전자"]}]}
    records, _, _ = rss.collect_feeds(
        cfg, lambda u: rss.FeedResponse(EDAILY_FEED.encode("utf-8"), "text/xml", u))
    assert len(records) == 3                       # 1단: 카테고리
    kept, dropped = s1_collect.filter_rss_records(records, keywords)
    assert len(kept) + dropped == 3                # 2단: 키워드
    assert dropped >= 1                            # 장류 담합은 우리 관심사가 아니다


# ── ⑧ 네이버 HUB 는 기본 비활성 ─────────────────────────────────────────────

def test_naver_hub_disabled_without_env(keywords, monkeypatch):
    called = []
    monkeypatch.setattr(s1_collect, "naver_hub_search",
                        lambda *a, **k: called.append(1) or [])
    assert s1_collect.naver_hub_enabled() is False
    _, _, cov = s1_collect.collect(keywords, use_rss=True, use_google=False,
                                   rss_cfg=make_cfg("a-ilbo"), rss_fetcher=fetcher)
    assert called == []                        # 호출조차 하지 않는다
    assert cov["source_tried"] == 1            # RSS 만 시도


def test_naver_hub_adapter_keeps_hub_contract():
    """결제수단 문제가 풀리면 env 만 채워 켠다 — 도메인·경로·헤더 계약 고정."""
    assert s1_collect.NAVER_HUB_HOST == "https://naverapihub.apigw.ntruss.com"
    assert s1_collect.NAVER_HUB_PATH == "/search/v1/news"
    src = (s1_collect.__file__)
    text = open(src, encoding="utf-8").read()
    assert "X-NCP-APIGW-API-KEY-ID" in text and "X-NCP-APIGW-API-KEY" in text


# ── ⑨ rss_sources.yaml 스키마 ───────────────────────────────────────────────

def test_rss_sources_yaml_schema():
    cfg = rss.load_sources()
    assert cfg.get("version") == 1
    assert cfg["sources"], "예시 소스가 최소 1건 있어야 한다"
    ids = [s["id"] for s in cfg["sources"]]
    assert len(ids) == len(set(ids)), "피드 id 중복"
    for s in cfg["sources"]:
        for key in ("id", "name", "tier", "section", "url", "enabled"):
            assert key in s, f"{s.get('id')}: {key} 누락"
        assert s["url"].startswith("http")
        assert "timeout_sec" in s and "max_items" in s      # defaults 병합


def test_run_writes_coverage_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(rss, "load_sources", lambda *a, **k: make_cfg("a-ilbo"))
    monkeypatch.setattr(rss, "fetch_response",
                        lambda url, timeout=15: rss.FeedResponse(fetcher(url), "text/xml", url))
    res = s1_collect.run(run_id="T-2", base_dir=tmp_path, use_google=False)
    cov = json.loads((tmp_path / "T-2" / "coverage.json").read_text(encoding="utf-8"))
    assert cov["by_outlet"] == {"가나일보": 1}
    assert res["records"][0]["track"] == "posco"
