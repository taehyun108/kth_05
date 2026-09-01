# STATUS — 진행 상태 (이어서 작업할 때 이 문서부터 읽는다)

브랜치: `claude/project-structure-analysis-lwl00r` · 최신 커밋 `c0201eb`
검증: **pytest 93 + node --test 44 = 137 green** (웹 5회·pytest 3회 연속 확인)

> 코드는 "키 없이 가능한 전 범위"가 끝난 상태다. 남은 것은 전부 **실데이터/키/실행환경(Z2)** 이 필요하다.
> Z2에서 무엇을 어떻게 돌리는지는 → **`docs/Z2-RUNBOOK.md`**.

---

## 1. 완료된 단계 (커밋 해시)

| 단계 | 내용 | 커밋 |
|---|---|---|
| 초기 | 프로젝트 파일 반입 | `d0f3903` |
| **P1** | 수집·정규화 (s1_collect·s2_normalize·relevance) | `5d63ce3` |
| P1 | Z2 실데이터 스모크 스크립트 | `716ec59` |
| **P2(L0)** | s4_analyze 규칙 태깅 + 추출 요약 | `ab41b8b` |
| **P3** | 프론트 + 인증 (레벨 게이트·필드 필터·/posco/) | `8e765f0` |
| **P4** | 카톡 발송 + 안전장치, INV-6 정밀화, 로그인 KV 추상화 | `0d1d058` |
| L1 | Ollama 어댑터(s4_l1) + P0-5 A/B 하네스 | `2b15c04` |
| **P7** | 오케스트레이터 DAG·체크포인트·재개 | `fabb574` |
| **P6** | SWOT + 주간 브리프 (s5_swot, /swot·/weekly) | `62bfbe8` |
| P6+ | 축 교정 기록(axis_corrections) + **P5a/b** 정책·통상 보드 | `afb4f71` |
| 품질 | 테스트 격리 + **로그인 코드 TTL 시계 버그 수정** | `a7efe70` |
| **P5c** | 일일 브리핑 메일 (Part A/B, HTML+텍스트) | `4fb97b1` |
| **P8** | 챗봇 구조 — RAG 코어 + 채널 스코프 게이트(법령 제외) | `f14dfc4` |
| 검증 | 전 구간 리허설 + `--only L0` 별칭 | `c0201eb` |

### 파일 지도 (무엇이 어디에)
```
pipeline/stages/
  common.py         canonical URL·기사 id·JSONL IO·KST
  relevance.py      posco_relevance L0 결정론 규칙(카톡 게이트, LLM 미사용)
  rss.py            [P1] ★RSS 정규화 계층★ — 매체별 포맷 편차 흡수(날짜·설명·CDATA·Atom)
  s1_collect.py     [P1] 수집 — 언론사 RSS(1순위)+구글 RSS(2순위)+커버리지, 네이버HUB 비활성
  s2_normalize.py   [P1] dedup·prescore·상한·트랙/게이트 1차
  s3_fetch.py       [P2] 크롤러 ★자리표시자(스킵)★ — Z2 스모크 후 구현
  s4_analyze.py     [P2 L0] 규칙 태깅 + 추출 요약
  s4_l1.py          [L1] Ollama 생성요약(kakao_summary·tone) — Ollama 없으면 스킵
  s5_swot.py        [P6] 이슈 클러스터·SWOT 축규칙(enforce_axes)·outlook
  stagers.py        [P5a/b] policy/dispute 단계 판정 + 엔티티 관리
  kakao_format.py   [P4] validate_kakao/validate_body (고정 포맷·존댓말)
  s7_dispatch.py    [P4] 카톡 라우터·안전장치·어댑터
  s7_mail.py        [P5c] 일일 브리핑 메일 Part A/B
pipeline/rss_sources.yaml  ★언론사 RSS 정의★ — Z2에서 실주소를 채운다(현재 예시 3건)
pipeline/orchestrator.py   [P7] DAG S0~S8, state/run-*.json, --resume/--only, 커버리지 리포트
lib/*.ts            [P3/P6/P8] 인증·API 레벨게이트·facets·card·ask(RAG)
app/                Next.js — login·posco·policy·trade·swot·weekly·api/*
scripts/
  smoke_collect.py  [Z2] 실데이터 스모크 — 매체별 파싱 편차 (→ RUNBOOK ②)
  ab_summarize.py   [Z2] P0-5 A/B 요약 품질 (→ RUNBOOK ④)
  rehearsal.py      전 구간 리허설(합성 30건)
tests/              pytest(파이프라인·INV) + tests/web(node --test)
```

---

## 2. 대기 중 — 무엇이 막고 있나

| 항목 | 막는 것 | 풀리면 할 일 |
|---|---|---|
| **`rss_sources.yaml` 실주소** | 전자신문 2건만 실호출 확인(`verified: true`). 연합뉴스·Federal Register 등 나머지는 미확인 | Z2에서 주소 확인 → 스모크로 파싱 편차·신선도 확인 → `verified: true` |
| **`keywords.yaml` 음극재 사전** | 실호출에서 음극재 기사 탈락 확인(아래 §7) | `must` 에 음극재/양극재 계열 추가 여부 결정 (물량 영향 있음 — 사람 판단) |
| **s3_fetch 실크롤러** | Z2 스모크 결과(실응답 필드 매핑·인코딩 미검증) | 스모크 리포트 → trafilatura→readability→newspaper3k 구현 |
| **L1 모델 확정** | P0-5 A/B 미실행(Ollama·실기사 20건 필요) | 포맷 통과율+사람 채점 → 모델·프롬프트 확정 |
| **카톡 실발송** | 카카오 오픈채팅 API 승인 + L1 미확정(현재 전부 extractive→스킵) | 승인 후 `dispatch_routes.yaml`의 `room_id_env`만 채움 |
| **P5d 법령** | 국가법령정보센터 Open API 인증키 | laws.json 엔티티 + law-analyst + 의견제출 D-14 알림 |
| **P8 RAG 품질** | 실기사 없이 검색 정확도 튜닝 불가 | 스코어링 가중치·슬롯 사전 튜닝 |
| **메일 실발송** | 사내 배포 리스트 수신 허용/화이트리스트(P0-6) | SMTP env 채우고 단계적 검증(1주 본인→팀→리스트) |
| **Vercel 배포** | 플랜/사내 반출 심의(P0-7), `npm install` 필요 | 배포 후 도메인·세션 확인 |

---

## 3. 다음에 할 일 (우선순위)

0. **`pipeline/rss_sources.yaml` 에 실제 언론사 RSS 주소 입력** — 수집 소스가 RSS 1순위로 바뀌었다. 이게 비면 수집 자체가 안 돈다. (`docs/Z2-RUNBOOK.md` ②-1)
1. **Z2 스모크 실행** → 매체별 파싱 편차 표 확인 → `rss.py` 보강 → `s3_fetch` 크롤러 착수. (RUNBOOK ②③)
2. **P0-5 A/B 실행** → L1 모델 확정 → `OLLAMA_MODEL` 고정, 프롬프트 조정. (RUNBOOK ④⑤)
3. 카카오 API 승인되면 `dispatch_routes.yaml` `kakao-team.enabled: true` + `KAKAO_OPENLINK_ID`. **먼저 섀도 운영 2주**(개인 채널) 후 단체방.
4. 법령 인증키 오면 **P5d**(laws.json·law-analyst·의견제출 마감 알림 — 이 트랙에서 가장 실용적).
5. 메일 도달성 검증(P0-6) 후 실발송 전환.
6. Vercel 배포(P0-7) — `npm install && npm run build`.

---

## 4. 리허설 결과 요약 (합성 30건이 각 스테이지에서 어떻게 흐르나)

`python -m scripts.rehearsal` — posco 8·battery 10·policy 7·trade 5.

```
S1 수집     30   (시드)
S2 정규화   30 → 30   dedup 0·상한컷 0 (합성이라 중복·초과 없음)
S3 크롤링   skip      (미구현 — 스니펫 degrade)
S4 분석     30 (L0)   impact mid 19·high 11
S4L1 생성   9 enrich  ★posco_relevance≠none 만★ (21 not_target)
S5 이슈     27 이슈·정책 7·분쟁 5   (합성은 토픽이 흩어져 대부분 단건 클러스터)
S6 발행     30   articles.json (L0:21 · L1:9)
S7 발송     카톡 0(route disabled) · 메일 Part A 9 + Part B 12
```

**핵심 확인:**
- **카톡 대상 = 포스코 언급분(primary) 9건 → `daily_limit:8` → 1 overflow → 정확히 8건.** 의도한 기사만 나간다.
- **`--only L0`: 30건 전부 L0로 발행(INV-6), 카톡 0**(전부 extractive → 스킵) — 정상.
- 리허설이 잡아낸 것: 초기 30→28은 파이프라인이 아니라 **합성 데이터 URL 충돌**(policy 20–26 ↔ trade 25–29)이었고 dedup-L1이 올바르게 병합. fixture를 고쳐 30→30.

---

## 5. 알려진 제약 / 함정

- **샌드박스 네트워크 차단**: 이 개발환경은 아웃바운드가 막혀 있다. `s1_collect`·스모크·A/B는 **Z2에서만** 실제 동작한다. 여기선 fail-soft로 0건.
- **카카오 승인 대기**: `dispatch_routes.yaml`의 `kakao-team.enabled: false` 유지. `DisabledKakaoAdapter`라 승인 전엔 어댑터 호출조차 안 된다(킬 스위치).
- **L1 미확정 → 카톡 실발송 0건**: L0 추출 요약은 반말이라 `validate_kakao` 통과 못 함(INV-10). L1(Ollama)이 존댓말 `kakao_summary`를 생성해야 카톡이 나간다. 그 전까지는 웹·메일만 발행(INV-6).
- **테스트 실행**: `bash ci-guard.sh`(pytest+INV grep) / `npm run test:web` 또는 `node --test "tests/web/**/*.test.ts"`. 앱 빌드(`next build`)는 `npm install` 필요 → Z2/Vercel에서.
- **상태 파일 격리**: 테스트는 `PNB_STATE_DIR`로 tmp 격리. 실 `pipeline/state/`·`data/*.json`은 `.gitignore`(시드는 `*.sample.json`만 추적).
- **수집 커버리지는 리포트로만 보인다**: RSS는 등록한 매체만 본다. S8 리포트의 `죽은 피드 의심`·`RSS 미등록 매체 후보`를 주기적으로 볼 것. 안 보면 조용히 누락된다.
- **INV 절대 완화 금지**: 특히 INV-3/6/7/8/10. 발송은 fail-closed, SWOT은 웹에서만, 카톡은 고정 포맷.

---

## 6. 변경 이력 — 수집 소스 재설계 (2026-09)

**무엇이 바뀌었나:** 검색 API 기반 수집 → **언론사 RSS 직접 구독 1순위**.

| 소스 | 판정 | 사유 |
|---|---|---|
| 네이버 검색 API | **탈락(어댑터만 비활성 보존)** | 2026-06 NAVER API HUB 이관, 2026-07-31 개발자센터 신규 신청 종료. 네이버클라우드 계정 + **결제수단 등록** 필요 → 쓰지 않기로 결정 |
| 빅카인즈 Open API | **후보 제외** | 2025년 **유료 전환** + **기사 재배포 금지 조항** |
| **언론사 RSS 직접 구독** | **1순위 채택** | 키 불요·원문 URL 직수신·중계링크 처리 불필요 |
| 구글 뉴스 RSS | 2순위 보조 | 1순위가 못 잡는 매체 보강. 차단 시 fail-soft + 운영 알림 |

**구조가 어떻게 달라졌나 (검색 API와 근본적으로 다르다)**
- 질의가 아니라 **피드 전체를 받아 `keywords.yaml` 로 거른다.** (`filter_rss_records`)
- 매체마다 포맷이 달라 **정규화 계층(`pipeline/stages/rss.py`)** 을 새로 뒀다 — RSS/Atom, 날짜 5종, description 폴백 체인, CDATA·태그·엔티티, `<link href>`, `category term`.
- **등록한 매체만 보이는 것이 유일한 약점**이라 커버리지 감시를 붙였다: `coverage.json` + S8 리포트(매체별 건수·이번 실행 0건 피드·연속 0건 3회 이상 **죽은 피드 의심**·구글로만 잡힌 **RSS 미등록 매체 후보**).
- 실패 정책: **피드별 fail-soft, 전 소스 실패 시에만 S1 `failed`.**
- 네이버 경로는 **삭제하지 않고 HUB 방식 어댑터로 비활성 보존** — `naverapihub.apigw.ntruss.com` `/search/v1/news`, 헤더 `X-NCP-APIGW-API-KEY-ID`/`X-NCP-APIGW-API-KEY`. `NAVER_HUB_KEY_ID`/`NAVER_HUB_KEY` 를 채우면 그때 켜진다(비면 호출조차 안 함).

**검증:** `tests/test_p1b_rss.py` 24건 — pubDate 3종+ISO/naive, description 없는 피드, CDATA 제목, Atom 폴백, 피드별 fail-soft, 전 소스 실패 신호, 커버리지·죽은 피드·미등록 매체, HUB 비활성, `rss_sources.yaml` 스키마.

---

## 7. 실호출 검증 (2026-09-01, 전자신문)

샌드박스는 아웃바운드가 막혀 있어 **Firecrawl 경유로 실제 호출**했다. Z2에서는 직접 호출로 재확인할 것.

| 대상 | 결과 |
|---|---|
| `https://www.etnews.com/rss/` (공식 RSS 목록) | **200** · 40개 섹션 주소 확보 |
| `https://rss.etnews.com/Section902.xml` | **200 · text/xml** · RSS 2.0 · 30건 · 당일 기사 · 파싱 정상 |
| `https://rss.etnews.com/06064.xml` (전자>소재) | **200 · text/xml** · 50건 · 파싱 정상 · ⚠️ **최신 기사 2026-06-25 = 68일 정체** |

**섹션 번호 정정:** `Section902.xml` 은 배터리가 아니라 **'뉴스속보'**(전 분야 혼재)다.
플레이스홀더에 `section: battery` 로 적어 둔 추정이 틀렸다. 배터리·소재는 `06064.xml`(소재), `06062.xml`(부품).

### 이 검증이 잡아낸 것 (합성 피드로는 안 나왔다)

1. **정체된 피드 — 새 고장 모드.** 200 OK, 항목 50건, 파싱 정상인데 두 달째 갱신이 없다.
   기존 '죽은 피드' 감시는 **0건**만 보므로 이 피드는 영원히 정상으로 보인다.
   → `coverage.stale_feeds` (최신 기사 14일 경과) 신설 + S8 리포트 노출 + 테스트 고정.
2. **channel `<image>` 블록.** 전자신문은 channel 안에 `<image><title><link>` 를 둔다.
   `.//title` 류로 긁었으면 매 실행마다 가짜 기사 1건이 섞였을 것. 현재 파서는 `.//item` 기준이라 무사 — 회귀 테스트로 고정.
3. **단일 자릿수 일자 RFC822** (`Tue, 1 Sep 2026`) — 정상 파싱 확인.
4. **`<category>` 가 아예 없다** — 필터가 제목·설명만으로 동작해야 함을 확인.
5. **커버리지 구멍(사람 판단 필요).** `동화일렉트로라이트, 건식 기반 음극 소재 개발 국책과제` 가 **탈락**했다.
   `keywords.yaml` battery/tech 의 must 가 `건식전극`·`실리콘음극` 이라 띄어쓴 '건식 기반 음극'과 매칭되지 않는다.
   음극재는 퓨처엠 주력이라 놓치면 안 되는 건이지만, `음극재`·`양극재` 를 must 에 넣으면 물량이 크게 늘어난다 → **사전 확장 여부는 결정 필요.**
   현재는 탈락하는 사실을 테스트로 고정해 뒀다(사전을 넓히면 그 테스트가 깨지며 변화가 드러난다).
