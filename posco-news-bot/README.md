# posco-news-bot

포스코 그룹·이차전지 산업·정책/법령·통상 뉴스 자동 수집·분석·배포 시스템.

## Claude Code로 시작하기

```bash
claude
> ROADMAP.md 의 P1 단계를 구현해줘
```

`CLAUDE.md`가 자동 로드되어 불변 규칙과 구조를 인식한다.
상세 명세는 `docs/INDEX.md`에서 작업별로 골라 읽는다.

## 파일 구성

```
CLAUDE.md         항상 로드되는 규칙·구조·용어  (141줄)
ROADMAP.md        P0~P8 단계별 착수 순서와 완료 기준
docs/INDEX.md     작업 유형별 문서 색인
docs/00~12        상세 명세
pipeline/
  keywords.yaml        T1~T4 키워드 + posco_entities (카톡 게이트 사전) + track_lang
  dispatch_routes.yaml 발송 라우팅
  stages/
    common.py          canonical URL·기사 id·JSONL IO·KST (공통)
    relevance.py       posco_relevance L0 결정론 규칙 (카톡 게이트, LLM 미사용)
    rss.py             [P1] RSS 정규화 계층 (매체별 포맷 편차 흡수)
    s1_collect.py      [P1] 수집 — 언론사 RSS(1순위) + 구글 뉴스 RSS(2순위)
    s2_normalize.py    [P1] 정규화·dedup·prescore·상한·게이트 1차
scripts/
  smoke_collect.py     [Z2] 실데이터 스모크 — s1_collect 실응답 검증
tests/
  test_invariants.py   INV 자동 검증
  test_p1_collect.py   P1 완료기준 검증
  fixtures/            실데이터 스모크 산출 (메타+발췌만, INV-5)
ci-guard.sh       INV grep 검사 + 테스트 실행
```

## 검증

```bash
bash ci-guard.sh                    # 파이프라인 INV grep + pytest (P1·P2·P4)
npm run test:web                    # 웹(인증·API·프론트) 테스트 — node --test, 의존성 설치 불요
```

## 발송 (P4 — 카톡·안전장치)

```
pipeline/stages/
  kakao_format.py    validate_kakao (고정 포맷·존댓말 종결 강제, INV-10) — 유일 소스
  s7_dispatch.py     라우터(INV-4)·안전장치(킬스위치·crisis 보류·이상감지·상한)·어댑터
pipeline/dispatch_routes.yaml  kakao-team.enabled:false (승인 후 true), room_id_env 만 채우면 됨
```

- **INV-6 발송 정밀화**: 발행은 항상 L0로(웹·메일). **카톡은 존댓말 포맷 충족 건만** —
  L0 추출 요약(`summary_method=extractive`)만 있는 건은 카톡 스킵 + 운영 리포트에 건수.
- 카톡 어댑터는 인터페이스만(`KakaoAdapter`). 승인 전엔 `DisabledKakaoAdapter` — enabled:false 면
  어댑터를 호출조차 하지 않는다(킬 스위치). 승인되면 `room_id`만 채워 실 구현체를 붙인다.

## 웹 (P3 — 프론트 + 인증)

Next.js App Router. **보안·필터 로직은 `lib/*.ts`(프레임워크 비의존)** 에 있고,
`app/`·`middleware.ts` 는 얇은 어댑터다. 그래서 `next` 설치 없이도 `node --test` 로
핵심을 검증한다(Node 22의 TS 타입 스트리핑).

```
lib/
  levels.ts      접근 레벨(L0/L1/L2) · rank/atLeast
  session.ts     서명 세션 쿠키(HMAC) · 완전검증(verify)/Edge용 readClaims
  allowlist.ts   이메일 → 레벨 (사내 도메인=L1, 허용목록=L2)
  auth.ts        6자리 코드 수명주기(만료·5회·일회성·논스·발급제한)
  guard.ts       requireLevel · safeNext(오픈 리다이렉트 방지)
  fields.ts      L2_ONLY 필드 제거 (INV-8)
  api.ts         articlesResponse(L1 필터)/issuesResponse(L2 게이트 403)
  facets.ts      facets 필터(그룹간 AND/그룹내 OR) · visiblePills(모바일 pill 축소)
  card.ts        카드 배지(⚙️ 규칙요약) · INV-6 optional 필드 안전화
middleware.ts    미인증 → /login?next= 리다이렉트 (실검증은 /api/*)
app/api/         articles·policies·disputes(L1: board 축약) · issues·analysis·weekly(L2) · auth/*
app/             login · posco · policy(국가×이슈 보드) · trade(부과국×대상국 보드) · swot/weekly(L2)
data/            *.sample.json (개발 시드) — 실데이터 *.json 은 .gitignore, public/ 아님
```

로컬 실행(Z2, 네트워크 필요):
```bash
npm install
export SESSION_SECRET=... ALLOWED_EMAIL_DOMAINS=poscofuturem.com L2_ADMIN_EMAILS=you@…
npm run dev        # http://localhost:3000  (코드 발송은 SMTP 미설정 시 서버 콘솔 출력)
```

> 인증 경계는 **서버**다(INV-8). L1 응답에는 L2 필드를 담지 않고(숨김이 아니라 부재),
> 데이터는 `data/`(서버 fs)에서만 읽으며 `public/` 에 JSON 을 두지 않는다.

## P1 파이프라인 실행

```bash
python -m pipeline.stages.s1_collect --dry-run          # 네트워크 없이 수집 계획 확인
python -m pipeline.stages.s1_collect --run-id <run_id>  # 수집 → raw/<run_id>/collected.jsonl
python -m pipeline.stages.s2_normalize --run-id <run_id> # 정규화 → raw/<run_id>/normalized.jsonl
```

## 실데이터 스모크 (Z2 외부망 PC에서 실행)

합성 피드로는 검증 못 하는 **매체별 RSS 포맷 편차**(날짜 포맷·description 유무·
CDATA/HTML 태그·인코딩·링크 형태)를 확인한다. 상세 절차는 `docs/Z2-RUNBOOK.md` ②.

```bash
# 1) pipeline/rss_sources.yaml 에 실제 언론사 RSS 주소를 채운다 (수집 키는 필요 없다)

# 2) 스모크 실행 — 활성 피드 전체, 최근 24시간
python -m scripts.smoke_collect
#   옵션: --feed <피드id>  --hours 48  --with-google  --max-queries N
```

출력:
- **stdout 리포트** — ★매체별 파싱 편차 표★(건수·날짜 파싱 실패·설명 결손·링크 결손·
  분류 결손·텍스트 이상), 키워드 통과율, 중복 canonical 군, RSS 미등록 매체 후보,
  fail-soft 오류. 원본>0 · 필수필드 결손 0 · 텍스트 이상 0 이면 `판정: PASS`.
- `tests/fixtures/collect_rss_<feed>.sample.json` — **커밋 대상**.
  메타데이터(제목·URL·발행시각·매체·소스) + **200자 이내 발췌만** (INV-5: 본문 전문 금지).
- `cache/smoke/raw-rss-*.jsonl` — 원본 응답. `cache/` 는 `.gitignore` 라 **커밋되지 않는다**.

> 리포트의 매체별 편차 표를 알려주면 그에 맞춰 정규화 계층(`rss.py`)을 보강한다.

## 착수 전 확인

- [ ] 카카오 오픈채팅 API 사용 신청 (승인 전엔 `dispatch_routes.yaml` → `kakao-team.enabled: false`)
- [ ] 국가법령정보센터 Open API 인증키
- [ ] `keywords.yaml` 의 `posco_entities`·`futurem_products` 검토 — **카톡 발송 게이트의 근거**
- [ ] Vercel 플랜 및 내부 분석자료 외부 저장 정책 (docs/11-decisions.md P0-7)
- [ ] Ollama 한국어 요약 품질 실측 (docs/11-decisions.md P0-5)
