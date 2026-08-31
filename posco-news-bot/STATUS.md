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
  s1_collect.py     [P1] 수집(네이버 fail-soft + 구글 RSS, 트랙 언어)
  s2_normalize.py   [P1] dedup·prescore·상한·트랙/게이트 1차
  s3_fetch.py       [P2] 크롤러 ★자리표시자(스킵)★ — Z2 스모크 후 구현
  s4_analyze.py     [P2 L0] 규칙 태깅 + 추출 요약
  s4_l1.py          [L1] Ollama 생성요약(kakao_summary·tone) — Ollama 없으면 스킵
  s5_swot.py        [P6] 이슈 클러스터·SWOT 축규칙(enforce_axes)·outlook
  stagers.py        [P5a/b] policy/dispute 단계 판정 + 엔티티 관리
  kakao_format.py   [P4] validate_kakao/validate_body (고정 포맷·존댓말)
  s7_dispatch.py    [P4] 카톡 라우터·안전장치·어댑터
  s7_mail.py        [P5c] 일일 브리핑 메일 Part A/B
pipeline/orchestrator.py   [P7] DAG S0~S8, state/run-*.json, --resume/--only
lib/*.ts            [P3/P6/P8] 인증·API 레벨게이트·facets·card·ask(RAG)
app/                Next.js — login·posco·policy·trade·swot·weekly·api/*
scripts/
  smoke_collect.py  [Z2] 실데이터 스모크 (→ RUNBOOK ②)
  ab_summarize.py   [Z2] P0-5 A/B 요약 품질 (→ RUNBOOK ④)
  rehearsal.py      전 구간 리허설(합성 30건)
tests/              pytest(파이프라인·INV) + tests/web(node --test)
```

---

## 2. 대기 중 — 무엇이 막고 있나

| 항목 | 막는 것 | 풀리면 할 일 |
|---|---|---|
| **s3_fetch 실크롤러** | Z2 스모크 결과(실응답 필드 매핑·인코딩·페이징 미검증) | 스모크 리포트 → trafilatura→readability→newspaper3k 구현 |
| **L1 모델 확정** | P0-5 A/B 미실행(Ollama·실기사 20건 필요) | 포맷 통과율+사람 채점 → 모델·프롬프트 확정 |
| **카톡 실발송** | 카카오 오픈채팅 API 승인 + L1 미확정(현재 전부 extractive→스킵) | 승인 후 `dispatch_routes.yaml`의 `room_id_env`만 채움 |
| **P5d 법령** | 국가법령정보센터 Open API 인증키 | laws.json 엔티티 + law-analyst + 의견제출 D-14 알림 |
| **P8 RAG 품질** | 실기사 없이 검색 정확도 튜닝 불가 | 스코어링 가중치·슬롯 사전 튜닝 |
| **메일 실발송** | 사내 배포 리스트 수신 허용/화이트리스트(P0-6) | SMTP env 채우고 단계적 검증(1주 본인→팀→리스트) |
| **Vercel 배포** | 플랜/사내 반출 심의(P0-7), `npm install` 필요 | 배포 후 도메인·세션 확인 |

---

## 3. 다음에 할 일 (우선순위)

1. **Z2 스모크 실행** → 리포트 확인 → `s3_fetch` 크롤러 착수. (`docs/Z2-RUNBOOK.md` ②③)
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
- **INV 절대 완화 금지**: 특히 INV-3/6/7/8/10. 발송은 fail-closed, SWOT은 웹에서만, 카톡은 고정 포맷.
