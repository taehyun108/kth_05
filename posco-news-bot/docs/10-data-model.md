# 10 — 데이터 모델 · 저장소 구조

## 5. 데이터 모델

### 5.1 `data/articles.json` — PUBLIC

```jsonc
{
  "schema_version": "1.0",
  "generated_at": "2026-08-26T07:20:00+09:00",
  "run_id": "20260826-0700",
  "outlets": ["연합뉴스", "이데일리", "Reuters", "Federal Register"],
  "counts": {
    "total": 98,
    "by_track": { "posco": 12, "battery": 54, "policy": 32 },
    "by_tone": { "positive": 21, "neutral": 62, "negative": 14, "crisis": 1 },
    "kakao_sent": 9
  },
  "articles": [
    {
      "id": "2026-08-26-a3f9c1d2e8",
      "date": "2026-08-26",
      "published_at": "2026-08-26T06:12:00+09:00",
      "title": "美 재무부, 45X 세액공제 음극재 적격비용 개정안 공고",
      "title_slug": "us-45x-anode-cost-amendment",
      "outlet": "Federal Register",
      "outlet_tier": 1,
      "source_type": "gazette",        // news | press_release | gazette | report
      "url": "https://...",
      "sources": ["google", "federal_register"],
      "lang": "en",
      "track": "policy",
      "also_tracks": [],
      "track_ambiguous": false,
      "category": "pol-us",
      "companies": [],
      "countries": ["US"],
      "topics": ["세액공제", "45X", "음극재"],
      "facets": ["track:policy","cat:pol-us","country:US","topic:세액공제","topic:45X","topic:음극재"],
      "policy_stage": "proposed",
      "dispute_stage": null,
      "affects_futurem": false,
      "posco_relevance": "none",
      "tone": "neutral",
      "impact": "high",
      "summary": "음극재 생산에 투입되는 원료비의 적격 범위를 축소하는 개정안을 공고했습니다.",
      "bullets": ["의견수렴 60일", "흑연 정제비용 제외 검토", "2027 과세연도 적용 예정"],
      "issue_id": "2026-W35-us-45x-amendment",
      "detail_url": "articles/2026-08-26-a3f9c1d2e8.html",
      "dispatch": { "routes": ["tg-policy"], "kakao_rooms": [], "mail": false },
      "paywall": false,
      "crawl_status": "ok",
      "dedup_of": null,
      "dup_count": 3
    }
  ]
}
```

> ❌ **public에 없는 필드:** `body`, `futurem_implication`, `swot_axis`, `sector_impact`, `frame`, `tone_evidence`, `policy_ask_hint`, `fact_check_flags`

### 5.2 `private/data/analysis.json` — PRIVATE

```jsonc
{
  "schema_version": "1.0",
  "run_id": "20260826-0700",
  "items": [
    {
      "id": "2026-08-26-a3f9c1d2e8",
      "sector_impact": "direct",
      "futurem_implication": "북미 음극재 세액공제 수취액이 직접 감소할 수 있으며, 원가 데이터 체계 정비가 시급합니다.",
      "swot_axis": "T",
      "policy_ask_hint": "적격비용 산정기준 명확화 요청 + 국내 세액공제 확대로 상쇄",
      "frame": "미국 자국 부가가치 요건 강화",
      "tone_evidence": ["...", "..."],
      "fact_check_flags": []
    }
  ]
}
```

### 5.3 `private/data/policies.json` — PRIVATE (T3 전용, v1.0 신규)

> 정책을 **엔티티**로 관리한다. 기사는 정책의 상태 변화 이벤트로 붙는다.

```jsonc
{
  "policies": [
    {
      "policy_id": "us-45x",
      "country": "US",
      "name": "IRA 45X 첨단제조 생산세액공제",
      "issue_tags": ["세액공제"],
      "current_stage": "proposed",
      "sector_impact": "direct",
      "affects": ["음극재", "양극재"],
      "timeline": [
        { "date": "2022-08-16", "stage": "enacted",   "article_ids": [], "note": "IRA 제정" },
        { "date": "2024-10-24", "stage": "effective", "article_ids": ["..."], "note": "최종 규칙 시행" },
        { "date": "2026-08-26", "stage": "proposed",  "article_ids": ["2026-08-26-a3f9c1d2e8"], "note": "음극재 적격비용 축소 개정안" }
      ],
      "our_position": "적격비용 범위 유지 필요",
      "linked_issue_id": "2026-W35-us-45x-amendment",
      "last_updated": "2026-08-26"
    }
  ]
}
```

**정책 보드(§4.6.5 ①)는 이 파일로 그린다.** 단, 보드에 필요한 최소 정보(국가·이슈·단계)는 public으로 별도 노출 가능 → `data/policy_board.json`(민감정보 제외 축약본)을 발행한다.

### 5.4 `private/data/issues.json` — PRIVATE (SWOT)

§4.5.3 스키마 그대로. 최상위에 `baseline: "포스코퓨처엠"`, `schema_version`, `generated_at`.

### 5.5 `pipeline/keywords.yaml`

```yaml
version: 1
tracks:
  posco:
    futurem:
      must:   ["포스코퓨처엠", "POSCO Future M"]
      expand: ["양극재","음극재","하드카본","천연흑연","전구체"]
      daily_cap: null            # 포스코 트랙은 상한 없음
  battery:
    cell-global:
      must:   ["CATL","BYD 배터리","Northvolt","파나소닉 배터리"]
      expand: ["나트륨이온","LFP","셀투팩"]
      lang:   ["ko","en"]
      daily_cap: 12
  policy:
    pol-us:
      must:   ["IRA 배터리","45X","FEOC","인플레이션 감축법"]
      expand: ["세액공제","관세","DOE 대출"]
      lang:   ["ko","en"]
      daily_cap: 10
      extra_sources:
        - type: federal_register
          query: "battery anode cathode critical minerals"
posco_entities:                  # posco_relevance 매칭 사전
  - 포스코
  - 포스코홀딩스
  - 포스코퓨처엠
  - 포스코인터내셔널
  - POSCO
outlet_tiers:
  1: [연합뉴스, 조선비즈, 매일경제, 한국경제, Reuters, Bloomberg, Federal Register]
  2: [이데일리, 전자신문, 머니투데이, 아시아경제]
negative_keywords: [테마주, 리딩방, 상한가, 목표주가]
```

---

---

### 6.2 저장소 구조

```
posco-news-bot/  (PRIVATE REPO · Vercel 배포)
├─ app/                            # Next.js App Router
│  ├─ login/page.tsx               # 로그인 코드 요청·검증
│  ├─ posco/page.tsx               # T1+T2 아카이브 (트랙 토글)      [L1]
│  ├─ policy/page.tsx              # T3 국가×이슈 보드·타임라인      [L1]
│  ├─ trade/page.tsx               # T4 부과국×대상국 분쟁 보드      [L1]
│  ├─ weekly/page.tsx              # 주간 브리프 + outlook           [L2]
│  ├─ articles/[id]/page.tsx       # 기사 상세                       [L1]
│  ├─ swot/page.tsx                # ★SWOT 4분면·교차전략·대응방안★  [L2]
│  ├─ dispatch/page.tsx            # ★발송 관리 패널·킬스위치·보류 승인★ [L2]
│  └─ api/
│     ├─ auth/{request,verify,logout}/route.ts
│     ├─ articles/route.ts         # [L1] 필드 필터링 후 서빙
│     ├─ policies/route.ts         # [L1]
│     ├─ disputes/route.ts         # [L1]
│     ├─ laws/route.ts             # [L1 보드] / 국가법령정보센터 프록시
│     ├─ weekly/route.ts           # [L2]
│     ├─ analysis/route.ts         # [L2]
│     ├─ issues/route.ts           # [L2] SWOT
│     └─ ask/route.ts              # RAG — 세션 레벨로 검색 범위 제한
├─ middleware.ts                   # ★세션 검증 · 미인증 → /login★
├─ lib/
│  ├─ session.ts                   # 서명 쿠키
│  ├─ allowlist.ts                 # L2 이메일 허용목록
│  └─ audit.ts                     # 감사 로그
├─ data/                           # ★public/ 아님 — 서버에서만 읽음★
│  ├─ articles.json                # [L1]
│  ├─ analysis.json                # [L2] 시사점·swot_axis
│  ├─ issues.json                  # [L2] SWOT
│  ├─ policies.json                # [L1 보드 / L2 our_position]
│  ├─ disputes.json                # [L1 보드 / L2 affects_futurem]
│  ├─ laws.json                    # [L1 보드 / L2 our_position]  (v2.0)
│  └─ weekly.json                  # [L2] 주간 브리프·outlook     (v2.0)
├─ public/                         # ★JSON 절대 두지 않는다 (INV-8)★
│  └─ (아이콘·CSS만)
├─ pipeline/                       # GitHub Actions에서 실행
│  ├─ keywords.yaml
│  ├─ dispatch_routes.yaml
│  ├─ orchestrator.py
│  ├─ stages/
│  │  ├─ s1_collect.py ~ s6_publish.py
│  │  ├─ s7_dispatch.py            # ← analysis/issues import 금지 (INV-3)
│  │  ├─ s7_mail.py                # ← 동일 금지 (INV-7)
│  │  └─ s8_report.py
│  ├─ agents/*.md                  # 프롬프트 (law_analyst, weekly_outlook 포함)
│  └─ state/run-<run_id>.json
├─ cache/                          # 원문 캐시 — .gitignore (INV-5)
├─ bot/telegram_bot.js
└─ .github/workflows/
   ├─ nightly.yml · morning.yml · dispatch.yml · weekly-swot.yml
   └─ ci-guard.yml                 # INV 검사

★ .gitignore 에 반드시: cache/, .env, state/
```

**데이터 갱신 → 배포 흐름**

```
GitHub Actions 파이프라인 실행
  → data/*.json 갱신 후 커밋·푸시
  → Vercel이 감지해 자동 재배포 (정적 JSON이라 빌드 수초)
```

> ⚠️ **배포 횟수 주의:** nightly 1 + morning 1 + intraday 3 + policy-watch 12 = **일 17회 배포**. 플랜별 일일 배포 한도에 근접할 수 있다.
> → `policy-watch`는 데이터만 커밋하고 **배포는 하루 4회로 묶는다**(커밋 메시지에 `[skip-deploy]` 또는 별도 브랜치 사용). 정책 폴링의 목적은 "긴급 텔레그램 푸시"이지 웹 즉시 반영이 아니다.
