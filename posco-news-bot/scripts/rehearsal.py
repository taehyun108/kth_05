#!/usr/bin/env python3
"""전 구간 리허설 — 합성 30건(4트랙)으로 S0~S8 완주 검증 (네트워크·키 없이).

- 수집(S1)만 시드로 대체(네트워크 필요)하고 S2~S8 을 실제로 돌린다.
- L1 은 모의 클라이언트로 포스코 관련 기사에 존댓말 요약을 붙여 카톡 대상이 보이게 한다.
- --only L0 비교: L1/L2·발송 없이 L0 만으로도 발행되는지(INV-6).
사용: python -m scripts.rehearsal
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import orchestrator as orch          # noqa: E402
from pipeline.stages import common, s7_dispatch     # noqa: E402

KST = common.KST
NOW = common.now_kst()
D = NOW.date().isoformat()

VALID_BODY = (
    "[{outlet}] 포스코퓨처엠이 관련 사안에 대응하고 있습니다. 업계에서는 이번 조치가 "
    "양극재·음극재 공급망에 미칠 영향을 주시하고 있으며, LG에너지솔루션(373220) 등 "
    "국내 배터리사도 상황을 예의주시하고 있습니다. 포스코퓨처엠은 북미와 국내 생산거점을 "
    "바탕으로 대응 방안을 검토하고 있습니다."
)


class MockL1:
    """Ollama 대역 — 포스코 관련 기사에 유효한 존댓말 카톡 요약을 생성."""
    def available(self):
        return True

    def generate(self, prompt: str) -> str:
        import re
        outlet_m = re.search(r"매체:\s*(.*)", prompt)
        outlet = (outlet_m.group(1).strip() if outlet_m else "연합뉴스")[:10] or "연합뉴스"
        idm = re.search(r'"id":\s*"([^"]*)"', prompt)     # 입력 id echo
        aid = idm.group(1) if idm else ""
        return json.dumps({"id": aid, "kakao_summary": VALID_BODY.format(outlet=outlet),
                           "tone": "neutral"})


def synth_articles() -> list[dict]:
    """4트랙 섞은 30건. 포스코 언급/미언급, 정책·통상 단계 다양하게."""
    arts: list[dict] = []

    def a(i, title, track, category, outlet, desc="", country=None):
        rec = {"id": f"{D}-r{i:02d}", "date": D,
               "published_at": (NOW).isoformat(), "title": title, "outlet": outlet,
               "url": f"https://news.example/{i}", "canonical_url": f"https://news.example/{i}",
               "sources": ["google"], "lang": "ko", "track": track, "also_tracks": [],
               "track_ambiguous": False, "category": category, "description": desc,
               "summary": desc or title, "summary_method": "extractive",
               "prescore": 5.0, "dedup_of": None, "dup_count": 0}
        if country:
            rec["countries"] = [country]
        return rec

    # T1 포스코 (8) — 포스코퓨처엠/홀딩스 등, primary
    posco = [
        ("포스코퓨처엠 광양 양극재 공장 증설 완료", "futurem"),
        ("포스코퓨처엠 음극재 신규 수주", "futurem"),
        ("포스코홀딩스 아르헨티나 리튬 2단계 준공", "holdings"),
        ("포스코퓨처엠 3분기 양극재 가동률 하락", "futurem"),
        ("포스코 광양제철소 안전사고 조사", "posco-steel"),
        ("포스코그룹 임단협 잠정합의", "group"),
        ("포스코인터내셔널 구동모터코아 확대", "international"),
        ("포스코DX 스마트팩토리 수주", "dx"),
    ]
    for i, (t, c) in enumerate(posco):
        arts.append(a(i, t, "posco", c, ["연합뉴스", "이데일리", "조선비즈"][i % 3], t))

    # T2 배터리 (10) — 일부 포스코 언급(mention), 일부 none
    battery = [
        ("LG에너지솔루션 유럽 46파이 수주", "cell-kr", "LG에너지솔루션 수주"),
        ("삼성SDI 전고체 파일럿 가동", "cell-kr", "삼성SDI 전고체"),
        ("CATL 나트륨이온 양산 성공", "cell-global", "CATL 나트륨이온"),
        ("에코프로비엠 양극재 증설", "mat-kr", "에코프로비엠 증설"),
        ("엘앤에프 하이니켈 공급계약", "mat-kr", "엘앤에프 계약"),
        ("배터리 소재 3사 실적 발표, 포스코퓨처엠 비교", "mat-kr", "포스코퓨처엠 비교군 언급"),
        ("탄산리튬 가격 반등", "raw", "리튬 가격"),
        ("전기차 캐즘 지속", "demand", "수요 둔화"),
        ("전고체 상용화 로드맵", "tech", "전고체 기술"),
        ("소성로 장비 수주", "equip", "장비 수주"),
    ]
    for i, (t, c, desc) in enumerate(battery):
        arts.append(a(10 + i, t, "battery", c, ["전자신문", "머니투데이", "한국경제"][i % 3], desc))

    # T3 정책 (7)
    policy = [
        ("美 재무부 45X 음극재 적격비용 개정안 공고", "pol-us", "Federal Register", "US", "gazette", "음극재 적격비용 축소"),
        ("이차전지 특별법 시행령 행정예고", "pol-law", "관보", "KR", "gazette", "제12조 세제지원"),
        ("정부 이차전지 특화단지 2차 지정 검토 중", "pol-kr", "연합뉴스", "KR", "news", "특화단지 검토"),
        ("EU 배터리규정 탄소발자국 공개 의무 시행", "pol-eu", "EUR-Lex", "EU", "gazette", "탄소발자국"),
        ("중국 신에너지차 보조금 개편", "pol-cn", "조선비즈", "CN", "news", "보조금"),
        ("일본 배터리 공급망 지원책 발표", "pol-global", "한국경제", "JP", "news", "공급망 지원"),
        ("SNE리서치 양극재 시장 전망", "pol-trend", "이데일리", "KR", "report", "시장 전망"),
    ]
    for i, (t, c, outlet, country, st, desc) in enumerate(policy):
        r = a(20 + i, t, "policy", c, outlet, desc, country)
        r["source_type"] = st
        arts.append(r)

    # T4 통상 (5)
    trade = [
        ("중국 흑연 수출통제 예비판정", "trade-export", "조선비즈", "CN", "news", "흑연 수출허가 통제"),
        ("미국 캐나다 철강 25% 관세 부과", "trade-tariff", "연합뉴스", "US", "news", "철강 관세"),
        ("반덤핑 예비판정 발표", "trade-remedy", "머니투데이", "US", "news", "반덤핑 예비판정"),
        ("FEOC 원산지 검증 강화", "trade-origin", "한국경제", "US", "news", "원산지 요건"),
        ("공급망 실사 의무 발효", "trade-supply", "전자신문", "EU", "news", "공급망 실사"),
    ]
    for i, (t, c, outlet, country, st, desc) in enumerate(trade):
        r = a(30 + i, t, "trade", c, outlet, desc, country)  # 30~ : policy(20~26)와 URL 겹침 방지
        r["source_type"] = st
        arts.append(r)
    return arts


def seed_run(base: Path, data: Path, run_id: str, articles: list[dict]) -> None:
    # 수집 결과를 collected.jsonl 로 시드하고 S1 을 성공 처리(네트워크 대체)
    common.write_jsonl(base / run_id / "collected.jsonl", articles)
    orch.save_state({"run_id": run_id, "mode": "daily", "status": "running", "params": {},
                     "stages": {"S1": {"status": "success", "output_count": len(articles)}},
                     "cost_total": {"api_calls": 0, "usd": 0.0}, "dispatch_log": []})


def run_once(mode, only, base, data, run_id, articles, llm):
    seed_run(base, data, run_id, articles)
    ctx = orch.make_context(mode, run_id, resume=True, only=only, no_dispatch=False,
                            base_dir=base, data_dir=data,
                            params={"base_url": "https://posco.example"},
                            extras={"llm_client": llm})
    return orch.run_pipeline(ctx)


def stage_table(state) -> str:
    rows = ["  stage  status    in→out    dur(s)  note"]
    for name in ("S0", "S1", "S2", "S3", "S4", "S4L1", "S5", "S6", "S7", "S8"):
        s = state.get("stages", {}).get(name)
        if not s:
            continue
        rows.append(f"  {name:5}  {s['status']:8}  {s.get('input_count',0)}→{s.get('output_count',0):<6}"
                    f"  {s.get('duration_sec',0):<6}  {s.get('note','')[:60]}")
    return "\n".join(rows)


def kakao_targets(data: Path, base: Path, run_id: str) -> list[str]:
    """카톡 발송 '대상'(enabled 가정) — 의도한 기사인지 눈으로 확인용."""
    src = base / run_id / "l1.jsonl"
    if not src.exists():
        src = base / run_id / "analyzed.jsonl"
    arts = list(common.read_jsonl(src)) if src.exists() else []
    route = {"id": "kakao-team", "channel": "kakao", "enabled": True, "room_id_env": "",
             "filter": {"any_of": [{"posco_relevance": "primary"},
                                   {"posco_relevance": "mention", "impact": ["high", "mid"]}]},
             "guards": {"require_relevance": True, "summary_len": [150, 350]}, "daily_limit": 8}
    plan = s7_dispatch.plan_kakao(arts, route, entities=s7_dispatch.posco_entities())
    return [f"{a['id']} · {a.get('title','')[:30]} ({a.get('posco_relevance')})" for _, _, a in plan.to_send]


def main() -> None:
    articles = synth_articles()
    tmp = Path(tempfile.mkdtemp(prefix="rehearsal-"))
    import os
    os.environ["PNB_STATE_DIR"] = str(tmp / "state")

    print("=" * 70)
    print(f"리허설: 합성 {len(articles)}건 (posco 8 · battery 10 · policy 7 · trade 5)")
    print("=" * 70)

    # ── 전체 실행 (L1 모의) ──
    base1, data1 = tmp / "raw1", tmp / "data1"
    st_full = run_once("daily", None, base1, data1, "reh-full", articles, MockL1())
    print("\n[전체 실행 · S0~S8]  status =", st_full["status"])
    print(stage_table(st_full))

    apath = data1 / "articles.json"
    art = json.loads(apath.read_text(encoding="utf-8"))
    print("\n  articles.json:", art["counts"]["total"], "건 ·",
          "by_track", art["counts"]["by_track"], "· level", art["counts"]["by_analysis_level"])
    issues = json.loads((data1 / "issues.json").read_text(encoding="utf-8"))["issues"]
    print("  issues.json:", len(issues), "이슈")
    pboard = json.loads((data1 / "policy_board.json").read_text(encoding="utf-8"))["policies"]
    dboard = json.loads((data1 / "dispute_board.json").read_text(encoding="utf-8"))["disputes"]
    print("  policy_board:", len(pboard), "· dispute_board:", len(dboard))
    mails = list((base1 / "reh-full" / "mail").glob("*.html"))
    print("  메일 HTML:", mails[0] if mails else "(없음)")

    print("\n  카톡 발송 대상(enabled 가정 · 포스코 언급분만이어야 함):")
    for t in kakao_targets(data1, base1, "reh-full"):
        print("    -", t)

    print("\n" + "-" * 70)
    print("[L0-only 실행 · --only L0]  (L1/L2·발송 없이 발행되는가 · INV-6)")
    base2, data2 = tmp / "raw2", tmp / "data2"
    # 시드 데이터를 쓰므로 S1(수집·네트워크)은 제외하고 L0 발행 경로만 실행.
    # (실운영의 `--only L0` 는 S1 을 포함해 신규 수집한다)
    st_l0 = run_once("daily", ["S0", "S2", "S3", "S4", "S6", "S8"], base2, data2, "reh-l0", articles, MockL1())
    print("  status =", st_l0["status"])
    print(stage_table(st_l0))
    art0 = json.loads((data2 / "articles.json").read_text(encoding="utf-8"))
    print("  articles.json:", art0["counts"]["total"], "건 · level", art0["counts"]["by_analysis_level"])
    print("  카톡 대상(L0-only, 전부 extractive → 0 이어야 정상):",
          len(kakao_targets(data2, base2, "reh-l0")))

    print("\n" + "=" * 70)
    print("S8 리포트 (전체 실행)")
    print("=" * 70)
    print(orch.build_report(st_full))
    print("\n(임시 산출물:", tmp, ")")


if __name__ == "__main__":
    main()
