# posco-news-bot

포스코 그룹·이차전지 산업·정책/법령·통상 뉴스를 자동 수집→요약→포스코퓨처엠 기준 영향도·SWOT 분석→다채널 배포하는 시스템.
**사람은 질문만 한다. 수집부터 발송까지 전 구간 자동.**

## 상세 명세 위치

작업 전 해당 문서를 읽을 것. CLAUDE.md는 규칙만, 상세는 docs/에 있다.

| 작업 | 문서 |
|---|---|
| 전체 개요·요구사항 대조 | `docs/00-overview.md` |
| 수집·정규화·중복제거 | `docs/01-collect.md` |
| 요약·논조·영향도 분석 | `docs/02-analyze.md` |
| SWOT·법령·주간 브리프 | `docs/03-swot-law.md` |
| 웹 프론트엔드 | `docs/04-frontend.md` |
| 인증·접근 제어 | `docs/05-auth.md` |
| **발송(카톡 포맷 고정)** | `docs/06-dispatch.md` |
| 메일 | `docs/07-mail.md` |
| 챗봇 | `docs/08-chatbot.md` |
| 오케스트레이터 | `docs/09-orchestrator.md` |
| 데이터 스키마 | `docs/10-data-model.md` |
| 미결정·리스크 | `docs/11-decisions.md` |
| 단계별 착수 순서 | `ROADMAP.md` |

## 불변 규칙 (INV) — 위반 금지

이 10개는 **제안·리팩터링·최적화 어떤 이유로도 완화하지 않는다.**
코드를 고치다 INV와 충돌하면, INV를 바꾸지 말고 **작업을 멈추고 물어볼 것.**

| INV | 규칙 | 검증 |
|---|---|---|
| 1 | 요약·크롤링은 전 트랙 공통. 트랙별 분기 없음 | `analyze.py` 단일 경로 |
| 2 | SWOT 기준점은 **항상 포스코퓨처엠** | `issues.json.baseline` 고정 |
| 3 | **SWOT은 웹에서만.** 발송 코드는 `issues.json`/`analysis.json`을 import조차 하지 않는다 | CI grep |
| 4 | 각 발송 대상은 `dispatch_routes.yaml`의 자기 규칙 기사만 받는다 | 라우트별 테스트 |
| 5 | 원문 전문(`body`)은 클라이언트 접근 경로에 두지 않는다 | `public/` 검사 |
| 6 | **L1·L2·L3는 선택 스테이지.** L0만으로도 발행·발송된다 | `--only L0` 테스트 |
| 7 | 메일도 SWOT 차단 대상 | `s7_mail.py` CI grep |
| 8 | **인증은 서버에서.** `public/`에 데이터 두지 않고 API가 세션 레벨로 필드를 걸러 응답 | 필드 누출 테스트 |
| 9 | 메일은 자체 완결적. 링크 없이도 업무가 된다 | 리뷰 |
| 10 | **카톡은 고정 포맷 외로 발송하지 않는다. 깨질 바에는 미발송** | `validate_kakao()` + 골든 샘플 |

## 절대 하지 말 것

- ❌ 카톡 메시지에 이모지·불릿·해시태그·논조 배지·헤더 메시지·목록형 축약 추가
- ❌ 카톡 발송 실패 시 "다른 형태로라도" 대체 발송
- ❌ `tone=crisis` 기사 자동 발송 (반드시 보류 → 사람 승인)
- ❌ 데이터 JSON을 `public/`에 배치
- ❌ 전체 데이터를 내려준 뒤 프론트에서 필터링
- ❌ `posco_relevance` 판정을 LLM에 맡기기 (결정론적 규칙이어야 함 — 발송 게이트)
- ❌ 기사 본문 전문을 `data/*.json`이나 git에 커밋
- ❌ 원문 문장을 그대로 옮긴 요약 (자체 문장 재작성)
- ❌ 백필 실행 시 발송 (`--mode backfill`은 `--no-dispatch` 강제)

## 4개 트랙

| 트랙 | 대상 | 웹 | 카톡 | 메일 |
|---|---|---|---|---|
| `posco` (T1) | 그룹 7개 계열사 | `/posco/` | ✅ | Part A |
| `battery` (T2) | 국내외 셀·소재·원료사 | `/posco/` | 포스코 언급 시 | Part A/B |
| `policy` (T3) | 지원제도·법령·행정예고·시장전망 | `/policy/` | 포스코 언급 시 | Part B |
| `trade` (T4) | 관세·수출통제·무역구제 | `/trade/` | 포스코 언급 시 | Part B |

**T3/T4 구분:** 돈을 주는 쪽이면 T3(지원제도), 문을 닫는 쪽이면 T4(관세·통제).
**카톡 발송 기준은 트랙이 아니라 `posco_relevance`.** 통상 기사여도 포스코퓨처엠이 언급되면 보낸다.

## 실행 계층 (LLM 비용 $0 — 외부 LLM API 키 불요)

| 계층 | 수단 | 담당 |
|---|---|---|
| **L0** | 규칙 엔진 (LLM 없음) | 수집·dedup·prescore·기업/국가/토픽 매칭·`posco_relevance`·`policy_stage`·추출 요약 |
| **L1** | Ollama 로컬 | Tier B 생성형 요약·논조 |
| **L2** | Claude Code 헤드리스 (`claude -p`, 구독 인증) | Tier A 시사점·이슈 클러스터링·SWOT·법령 분석·주간 outlook |
| **L3** | Groq (폴백) | PC 사용 불가 시 Tier A만 |

Groq 무료 티어는 물량을 못 감당한다(일 132만 토큰 필요 vs TPD 10만~50만). 대량 요약을 외부 API로 돌리지 말 것.

## 실행 환경

```
Z2 외부망 PC    파이프라인(Ollama·Claude Code) + SMTP 발송 + git push  ← 셀프호스트 러너
Vercel          웹 서빙 + 로그인(3단 레벨) + 챗봇 API
GitHub Actions  스케줄·수집·발송 (클라우드 러너는 L0만)
Z3 모바일       카톡 수신 · 웹 열람
```

## 스케줄 (07:00은 만드는 시각이 아니라 보내는 시각)

```
00:20 클라우드 L0     전일 확정분 수집·요약 → articles.json + 메일 초안
00:50 셀프호스트 L1·L2 논조·시사점 보강 → enrich 재발행
06:30 클라우드 L0     당일 새벽 증분 (카톡용)
06:40 재시도          L1·L2 미완료 시 1회
07:00 발송            메일 + 카톡(자동) + 텔레그램
월 07:30              주간 SWOT + outlook
매 2시간              policy-watch / law-watch (배포는 하루 4회로 묶음)
```

## 저장소 구조

```
app/            Next.js — login, posco, policy, trade, articles, swot(L2), weekly(L2), dispatch(L2)
app/api/        articles·policies·disputes·laws [L1] / analysis·issues·weekly [L2] / ask
middleware.ts   세션 검증
data/           ★public/ 아님★ articles·analysis·issues·policies·disputes·laws·weekly.json
public/         ★JSON 절대 두지 않음★
pipeline/       keywords.yaml · dispatch_routes.yaml · orchestrator.py · stages/ · agents/
cache/          원문 캐시 (.gitignore)
tests/          INV 검증 테스트
```

## 명령어

```bash
python pipeline/orchestrator.py --mode daily          # 일일 실행
python pipeline/orchestrator.py --mode daily --dry-run # 발송 없이 검증
python pipeline/orchestrator.py --resume <run_id>     # 실패 지점부터 재개
python pipeline/orchestrator.py --only L0             # L0만 (INV-6 테스트)
npm run test:inv                                       # INV 자동 검증
bash .github/ci-guard.sh                               # INV-3/5/7/8 grep 검사
```

## 용어

- `posco_relevance` — `primary`/`mention`/`none`. **카카오톡 발송의 유일한 게이트**
- `sector_impact` — 포스코 언급과 무관한 퓨처엠 사업 영향도. **카톡 게이트에 쓰지 않는다**
- `swot_axis` — 기사 단위 S/W/O/T 1개. 이슈 단위 4분면과 다른 층위
- Tier A/B/C — LLM 투입 등급. `posco_relevance ≠ none`은 **전량 Tier A**
- INV — 불변 규칙. 위반 시 작업 중단
- L0~L3 — 실행 계층
- Z1/Z2/Z3 — 사내망 / 외부망 / 모바일

## 코딩 규칙

- Python 3.11, 타입 힌트 필수
- 스테이지 간 통신은 **파일로만** (메모리 전달 금지 — 재개 가능성의 전제)
- 출력 파일이 존재하고 `input_hash`가 같으면 스킵 (멱등성)
- 건별 실패는 `errors[]`에 기록하고 계속. 스테이지 전체 실패만 중단
- 발송 경로는 **fail-closed** — 판정 불가 시 보내지 않는다
- LLM 호출은 JSON 강제 + 입력 id echo (배치 순서 뒤바뀜 방지)
