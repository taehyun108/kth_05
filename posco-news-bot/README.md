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
    s1_collect.py      [P1] 수집 — 네이버 API + 구글 뉴스 RSS
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
bash ci-guard.sh                    # INV grep + 전체 테스트 (pytest)
```

## P1 파이프라인 실행

```bash
python -m pipeline.stages.s1_collect --dry-run          # 네트워크 없이 수집 계획 확인
python -m pipeline.stages.s1_collect --run-id <run_id>  # 수집 → raw/<run_id>/collected.jsonl
python -m pipeline.stages.s2_normalize --run-id <run_id> # 정규화 → raw/<run_id>/normalized.jsonl
```

## 실데이터 스모크 (Z2 외부망 PC에서 실행)

합성 fixture 로는 검증 못 하는 **실제 네이버/구글 응답의 필드 매핑·인코딩·페이징**을
P2 착수 전에 확인한다.

```bash
# 1) 네이버 검색 API 키 설정 (없으면 구글 RSS 만으로 fail-soft 동작)
cp .env.example .env
#   .env 에 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 입력
#   발급: https://developers.naver.com/apps  (검색 > 뉴스)

# 2) 스모크 실행 — 기본: posco/futurem, 최근 24시간
python -m scripts.smoke_collect
#   옵션: --track battery --category cell-kr --hours 48 --no-naver --max-queries N
```

출력:
- **stdout 리포트** — 수집 건수, 소스별 분포, 24h 이내 건수, 필드 누락, 필수필드 결손,
  인코딩 이상(U+FFFD·미복원 엔티티·제어문자·NFC 불일치), 중복 canonical 군, fail-soft 오류.
  필수필드 결손·인코딩 이상이 0 이면 `판정: PASS`.
- `tests/fixtures/collect_<track>_<category>.sample.json` — **커밋 대상**.
  메타데이터(제목·URL·발행시각·매체·소스) + **200자 이내 발췌만** (INV-5: 본문 전문 금지).
- `cache/smoke/raw-*.jsonl` — 원본 응답. `cache/` 는 `.gitignore` 라 **커밋되지 않는다**.

> 리포트 결과(특히 필드 누락·인코딩 이상 유무)를 알려주면 그에 맞춰 P2(크롤링·요약)를 착수한다.

## 착수 전 확인

- [ ] 카카오 오픈채팅 API 사용 신청 (승인 전엔 `dispatch_routes.yaml` → `kakao-team.enabled: false`)
- [ ] 국가법령정보센터 Open API 인증키
- [ ] `keywords.yaml` 의 `posco_entities`·`futurem_products` 검토 — **카톡 발송 게이트의 근거**
- [ ] Vercel 플랜 및 내부 분석자료 외부 저장 정책 (docs/11-decisions.md P0-7)
- [ ] Ollama 한국어 요약 품질 실측 (docs/11-decisions.md P0-5)
