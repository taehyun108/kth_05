# ROADMAP — 단계별 착수 순서

각 단계는 **완료 기준을 자동 테스트로 통과**해야 다음으로 넘어간다.

---

## P0. 환경 + 신청 (3일) — 병행 진행

| # | 작업 | 비고 |
|---|---|---|
| 1 | **카카오 오픈채팅 API 사용 신청** | 심사 리드타임. 개발과 병행, 승인 전엔 `enabled: false` |
| 2 | 국가법령정보센터 Open API 인증키 신청 | 법령 트랙 전제 |
| 3 | 셀프호스트 러너 설치 (Z2 외부망 PC) | GitHub Actions self-hosted |
| 4 | Ollama 설치 + 후보 모델 2~3개 | 한국어 요약용 |
| 5 | `claude setup-token` | L2 헤드리스 인증 |
| 6 | **사전 3종 작성** | 아래 참조 — **코드보다 먼저** |

### 사전 3종 (이게 없으면 파이프라인이 무의미한 결과를 낸다)

| 파일 | 내용 | 쓰이는 곳 |
|---|---|---|
| `pipeline/keywords.yaml` → `posco_entities` | 계열사명·영문·약칭 | `posco_relevance` = 카톡 게이트 |
| `pipeline/keywords.yaml` → `tracks` | T1~T4 키워드 매트릭스 | 수집 범위 전체 |
| `pipeline/keywords.yaml` → `futurem_products` | 양극재·음극재·전구체·흑연·리튬·니켈 | `affects_futurem` 판정 |

**완료 기준:** 로컬에서 `claude -p --output-format json` 구조화 출력 성공 + 신청 접수 완료

---

## P1. 수집·정규화 (1.5주)

- `pipeline/stages/s1_collect.py` — 네이버 검색 API, 구글 뉴스 RSS(ko/en), 정부·기관 RSS
- `pipeline/stages/s2_normalize.py` — canonical URL, `id = 날짜+sha1(url)[:10]`, dedup L1·L2, prescore, 일일 상한
- 트랙 판정(T1~T4) + `posco_relevance` 1차 (규칙)

**완료 기준**
- [ ] 4트랙 수집 → dedup → 상한 컷이 동작
- [ ] 대표 기사·포스코 언급 기사가 상한에서 면제됨
- [ ] `posco_relevance` 나열 패턴 예외("국내 3사와 포스코퓨처엠 등")가 `none`으로 강등됨

참조: `docs/01-collect.md`

---

## P2. 크롤링·요약 (1.5주)

- `s3_fetch.py` — trafilatura→readability→newspaper3k, robots 준수, 도메인 큐
- `s4_analyze.py` — L0 규칙 태깅 + 추출 요약 → L1 Ollama 생성형 요약
- **P0-5 실측**: 실기사 20건으로 Ollama 모델 A/B

**완료 기준**
- [ ] 크롤링 성공률 ≥ 85%
- [ ] **L0만으로 아카이브가 완성됨** (INV-6)
- [ ] L1 요약 사실 오류 20건 중 ≤ 1건 — 미달 시 추출 요약 유지
- [ ] 토큰·소요시간 실측 완료

참조: `docs/02-analyze.md`

---

## P3. 프론트 + 인증 (1.5주)

- Next.js 앱, `middleware.ts`, 로그인 코드 인증
- `/api/*` 레벨별 서빙 + 필드 필터링
- `/posco/` 트랙 토글 + facets 필터 + 카드 그리드

**완료 기준**
- [ ] **L1 세션으로 `/api/issues` 호출 시 403**
- [ ] **`/api/articles` 응답에 L2 필드 부재** (`futurem_implication`, `swot_axis`, `body` 등)
- [ ] `public/`에 데이터 JSON 없음
- [ ] 링크 클릭 → 로그인 → 원래 기사로 복귀
- [ ] 모바일 정상

참조: `docs/04-frontend.md`, `docs/05-auth.md`

---

## P4. 발송 + 안전장치 (1.5주) ★분석 기능보다 먼저★

발송은 한 번 잘못 나가면 되돌릴 수 없다. 여기서 테스트로 고정한다.

- `dispatch_routes.yaml` 라우터
- 카카오 오픈채팅 API 연동 + **고정 포맷 + `validate_kakao()`**
- 안전장치 5종 (킬스위치·이상감지·섀도·로그·상한)
- 발송 관리 패널 `/dispatch/` (L2)

**완료 기준**
- [ ] 라우트별 필터 테스트 통과
- [ ] **포스코 미언급 기사가 카톡에 나가지 않음**
- [ ] **`tone=crisis` 건이 자동 발송되지 않고 보류됨**
- [ ] 킬 스위치(`enabled: false`) 즉시 반영
- [ ] `validate_kakao()` 골든 샘플 회귀 테스트 통과
- [ ] 포맷 위반 시 해당 건만 미발송, 나머지는 정상 발송
- [ ] **섀도 운영 1주 무사고**

참조: `docs/06-dispatch.md`

---

## P5. 정책·통상·법령 탭 (3.5주)

| 하위 | 산출 |
|---|---|
| P5a 정책 | `policies.json`, policy-stager, `/policy/` 국가×이슈 보드 |
| P5b 통상 | `disputes.json`, dispute-stager, `/trade/` 부과국×대상국 보드 |
| P5c 메일 | `s7_mail.py`, Part A(언론사별)/Part B(정책·통상), SMTP |
| P5d 법령 | `laws.json`, law-analyst, 국가법령정보센터 연동, **의견제출 마감 알림** |

**완료 기준**
- [ ] 보드 렌더 + 단계 배지 정확
- [ ] `affects_futurem` 필터 동작
- [ ] 행정예고 감지 → 조문 영향 분석 → **D-14 알림** 동작
- [ ] 전일 포스코 기사가 언론사별로 묶여 07:00 수신

참조: `docs/03-swot-law.md`, `docs/07-mail.md`

---

## P6. SWOT + 주간 브리프 (2주)

- issue-clusterer (T1~T4 혼합), swot-analyst, `/swot/` (L2)
- weekly-outlook, `/weekly/` (L2)

**완료 기준**
- [ ] 경쟁사 기사가 퓨처엠 **O/T로 정확히 배치** (S/W에 들어가지 않음)
- [ ] 이슈 id가 재클러스터링에도 안정적
- [ ] `outlook.likely` 항목에 근거 기사 id 필수
- [ ] SWOT이 카톡·메일·텔레그램에 나가지 않음 (CI grep)

참조: `docs/03-swot-law.md`

---

## P7. 오케스트레이터 (1주)

**완료 기준**
- [ ] 중간 실패 후 `--resume` 성공
- [ ] **PC 꺼진 상태에서 L0 단독 발행 성공**
- [ ] 재실행 시 중복 발송 없음 (`dispatch_log` 멱등)
- [ ] `--mode backfill`이 발송을 강제 차단

참조: `docs/09-orchestrator.md`

---

## P8. 챗봇 (1주)

**완료 기준**
- [ ] 근거 없는 질문에 "수집된 기사에 없습니다" 응답
- [ ] 모든 사실 주장에 기사 id 각주
- [ ] **텔레그램 세션에서 SWOT·시사점 출력 안 됨**
- [ ] 법령 검색이 아카이브 밖 조문도 조회

참조: `docs/08-chatbot.md`
