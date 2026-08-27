# 09 — 오케스트레이터 · 에이전트 · 프롬프트

> LLM 실행 계층(L0~L3)은 `docs/02-analyze.md` 참조.

## 11. 오케스트레이터 명세

### 11.1 설계 목표

| 목표 | 구현 |
|---|---|
| **재개 가능** | 스테이지별 체크포인트, 실패 지점부터 resume |
| **멱등성** | 같은 `run_id`로 재실행해도 중복 발송·중복 저장 없음 |
| **부분 실패 허용** | 소스 1개 실패가 전체를 죽이지 않음 (fail-soft) |
| **위험 지점 보수적** | 발송 게이트는 fail-closed |
| **관측 가능** | 실행 리포트 자동 생성 |
| **드라이런** | 발송 없이 전 과정 검증 |

### 11.2 DAG

```
                    ┌─────────────┐
                    │ S0 PREFLIGHT│  키·쿼터·디스크·스키마 검증
                    └──────┬──────┘
                           ▼
              ┌────────────────────────┐
              │ S1 COLLECT (병렬 3)     │
              │  ├ T1 posco            │ fail-soft
              │  ├ T2 battery          │ fail-soft
              │  └ T3 policy           │ fail-soft
              └────────────┬───────────┘
                           ▼  (최소 1개 트랙 성공 시 진행)
                    ┌──────────────┐
                    │ S2 NORMALIZE │  fail-hard
                    └──────┬───────┘
                           ▼
                    ┌──────────────┐
                    │ S3 FETCH     │  fail-soft (건별)
                    │  동시성 8    │
                    └──────┬───────┘
                           ▼
        ┌──────────────────────────────────────┐
        │ S4 ANALYZE (병렬)                     │
        │  S4a summarizer   ─┐                 │
        │  S4b tone-judge   ─┼→ merge          │ 건별 fail-soft
        │  S4c entity-tagger─┤   (id join)     │ ※S4c 실패 시 해당 건
        │  S4d futurem      ─┤                 │   카톡 발송 제외
        │  S4e policy-stager─┘ (T3만)          │
        └──────────────┬───────────────────────┘
                       ▼
          ┌────────────┴────────────┐
          ▼                         ▼
   ┌─────────────┐          ┌──────────────┐
   │S5 CLUSTER   │          │S6 PUBLISH    │  fail-hard
   │  +SWOT      │          │  PUBLIC      │
   │ (weekly만   │          └──────┬───────┘
   │  전체 실행) │                 ▼
   │ fail-soft   │          ┌──────────────┐
   └──────┬──────┘          │S7 DISPATCH   │  ★fail-closed★
          │                 │ kakao/telegram│
          ▼                 └──────┬───────┘
   ┌─────────────┐                 │
   │S5b PUBLISH  │                 │
   │  PRIVATE    │                 │
   └──────┬──────┘                 │
          └──────────┬─────────────┘
                     ▼
              ┌─────────────┐
              │ S8 REPORT   │  실행 리포트 + 알림
              └─────────────┘
```

> **핵심 배치 결정:** `S5 CLUSTER+SWOT`(private)과 `S7 DISPATCH`는 **형제 노드이며 서로 의존하지 않는다.** S7이 S5의 산출물을 입력으로 받을 수 없는 구조 자체가 INV-3의 물리적 보증이다.

### 11.3 스테이지 계약 (Node Contract)

각 스테이지는 아래를 준수한다.

```python
@dataclass
class StageResult:
    stage: str
    status: Literal["success", "partial", "failed", "skipped"]
    input_count: int
    output_count: int
    errors: list[dict]          # {item_id, error_type, message}
    artifacts: list[str]        # 산출 파일 경로
    duration_sec: float
    cost: dict                  # {api_calls, input_tokens, output_tokens, usd}
    checkpoint: str             # 재개 지점 식별자
```

**규칙**
- 스테이지는 **입력 파일 → 출력 파일** 로만 통신한다 (메모리 전달 금지). 재개 가능성의 전제다.
- 출력 파일이 이미 존재하고 `input_hash`가 같으면 **스킵**한다 (멱등성).
- 건별 실패는 `errors[]`에 기록하고 계속 진행. 스테이지 전체 실패는 예외로 중단.

### 11.4 상태 파일

`pipeline/state/run-20260826-0700.json`

```jsonc
{
  "run_id": "20260826-0700",
  "mode": "daily",              // daily | intraday | policy-watch | weekly | backfill | dryrun
  "started_at": "2026-08-26T07:00:03+09:00",
  "status": "running",          // running | success | partial | failed
  "params": { "since": "2026-08-25T07:00:00+09:00", "tracks": ["posco","battery","policy"] },
  "stages": {
    "S0": { "status":"success","duration_sec":2.1 },
    "S1": { "status":"partial","output_count":340,
            "errors":[{"source":"google_rss_en","error_type":"http_429"}] },
    "S2": { "status":"success","output_count":110 },
    "S3": { "status":"partial","output_count":104,
            "errors":[{"item_id":"...","error_type":"paywall"}] },
    "S4": { "status":"running","checkpoint":"batch_12/22" }
  },
  "cost_total": { "api_calls": 187, "usd": 0.94 },
  "dispatch_log": []            // S7 완료 후 발송 내역 (멱등 판정용)
}
```

### 11.5 실패 정책

| 스테이지 | 정책 | 실패 시 |
|---|---|---|
| S0 preflight | fail-hard | 즉시 중단, 알림 |
| S1 collect | **fail-soft (소스별)** | 최소 1개 트랙 성공 시 진행. 전부 실패 시 중단 |
| S2 normalize | fail-hard | 중단 (데이터 정합성 문제) |
| S3 fetch | fail-soft (건별) | `crawl_status: failed` 로 진행, 스니펫 degrade |
| S4 analyze | fail-soft (건별) | **단, `entity-tagger` 실패 건은 `posco_relevance=null` → S7에서 발송 제외** |
| S5 cluster/swot | fail-soft | 이전 `issues.json` 유지, 알림 |
| S6 publish | fail-hard | 중단 (부분 발행 금지) |
| S7 dispatch | **fail-closed** | 게이트 판정 불가 건은 발송 안 함. 발송 후 즉시 `dispatch_log` 기록 |
| S8 report | fail-soft | 리포트 없이 종료 |

**S7 멱등성 보장**
```python
# 발송 전 dispatch_log 확인 → 이미 보낸 article_id는 스킵
# 발송 성공 즉시 state 파일에 append (배치 종료 후 일괄 기록 금지)
# → 중간에 죽어도 재실행 시 중복 발송 없음
```

### 11.7 실행 모드

```bash
# 일일 실행
python orchestrator.py --mode daily

# 정책만 경량 폴링
python orchestrator.py --mode policy-watch --tracks policy

# 발송 없이 전 과정 검증
python orchestrator.py --mode daily --dry-run

# 실패 지점부터 재개
python orchestrator.py --resume 20260826-0700

# 특정 스테이지만
python orchestrator.py --resume 20260826-0700 --only S4,S6,S7

# 과거 데이터 백필 (발송 강제 차단)
python orchestrator.py --mode backfill --since 2026-07-01 --until 2026-08-25 --no-dispatch
```

> `--mode backfill`은 **`--no-dispatch`가 강제**된다. 백필 중 과거 기사가 카톡으로 쏟아지는 사고를 구조적으로 막는다.

### 11.8 실행 리포트 (S8)

```
[RUN 20260826-0700] daily · 성공(부분)  ⏱ 6분 12초  💰 $0.94

수집    340건  (google_rss_en 429 실패 — 해외 기사 누락 가능)
정규화  110건  (중복 55 · 네거티브 40 · 상한컷 135 제외)
크롤링  104건  성공 / 6건 실패(페이월 4, 타임아웃 2)
분석    104건  완료
발행    articles.json 98건 · policy_board.json 갱신
발송    카카오 9건 · 텔레그램 포스코12/산업54/정책8

⚠️  경고
 - google_rss_en 429 → 해외 소스 재시도 권장
 - track_ambiguous 7건 → 수동 확인 필요
 - swot review 미완료 이슈 3건
```

리포트는 텔레그램 `#운영-알림` 채널로 발송하고, `state/` 에 보관한다.

---

---

## 7. 에이전트 구성 (Claude Code Sub-agents)

| # | 에이전트 | 입력 | 출력 | 배치 | 분리 이유 |
|---|---|---|---|---|---|
| A1 | `collector` | keywords.yaml | collected.jsonl | — | LLM 미사용 (룰 기반) |
| A2 | `normalizer` | collected | normalized + prescore | — | LLM 미사용 |
| A3 | `crawler` | URL | cache json | — | LLM 미사용 |
| A4 | `summarizer` | 본문 | summary, bullets | **5건/호출** | 비용 절감 (단순 태스크) |
| A5 | `tone-judge` | 본문 | tone, impact, evidence | 1건/호출 | 요약과 합치면 **요약 문체에 논조가 오염** |
| A6 | `entity-tagger` | 본문+제목 | companies, countries, topics, posco_relevance, track검증 | 5건/호출 | 게이트 판정이 걸려 있어 **독립 검증 가능해야 함** |
| A7 | `futurem-analyst` | 본문+요약 | futurem_implication, swot_axis, sector_impact, policy_ask_hint | 3건/호출 | 기사 논조(A5)와 **우리 입장의 유불리는 다른 개념** |
| A8 | `policy-stager` | 본문 (T3만) | policy_stage, policy_id 매칭 | 5건/호출 | 정책 단계 판정은 도메인 특화 |
| A8b | **`law-analyst`** | 법령 원문·예고안 | 조문별 당사 영향, `affects_futurem`, 의견제출 포인트 | 법령 1건/호출 | **조문 단위 분석은 기사 분석과 전혀 다른 태스크** (v2.0) |
| A10b | **`weekly-outlook`** | 주간 이슈·법령 캘린더 | `scheduled`/`likely`/`monitoring` + 대응방안 | 주 1회 | 예측은 근거 검증 규칙이 별도로 필요 (v2.0) |
| A9 | `issue-clusterer` | 14일치 요약 | issue 후보 + 기존 이슈 매칭 | 배치 | — |
| A10 | `swot-analyst` | 이슈별 기사 요약 | SWOT + 전략 + 대응 + policy_ask | 이슈 1건/호출 | 기준점 고정 프롬프트 필요 |
| A11 | `fact-checker` | 본문 + 수치 주장 | fact_check_flags | 5건/호출 | 선택 실행 (impact=high만) |
| A12 | `publisher` | 전체 | JSON/HTML/메시지 | — | LLM 미사용 |

### 실행 계층 배치 (v1.1)

| 계층 | 에이전트 | 비고 |
|---|---|---|
| **L0 규칙** | A1 collector · A2 normalizer · A3 crawler · **A6 entity-tagger** · **A8 policy-stager** · A12 publisher | LLM 미사용. 사전·정규식·소스타입 기반 |
| **L1 로컬 LLM** | A4 summarizer (Tier B) · A5 tone-judge (Tier B) | Ollama |
| **L2 Claude Code** | A4·A5 (Tier A) · **A7 futurem-analyst** · A9 issue-clusterer · **A10 swot-analyst** · A11 fact-checker | 헤드리스, 구독 인증 |
| **L3 폴백** | A4·A5 (Tier A) | Groq — PC 사용 불가 시에만 |

> **A6 entity-tagger와 A8 policy-stager가 L0로 내려온 것이 v1.1의 큰 변화다.** `posco_relevance`는 카톡 발송 게이트라 **결정론적이어야 안전하다.** LLM 판정은 같은 입력에도 흔들리는데, 발송 여부가 실행할 때마다 달라지면 감사도 재현도 불가능하다. 사전 매칭 + 나열 패턴 예외 규칙이 이 자리에서는 LLM보다 낫다.

### 분리 원칙 (위반 시 발생하는 실제 증상)

| 합치면 안 되는 조합 | 증상 |
|---|---|
| `summarizer` + `tone-judge` | 부정 기사 요약이 부정적 문체로 나와 이후 중립 판정이 불가능 |
| `tone-judge` + `futurem-analyst` | "CATL 나트륨이온 양산 성공"이 `negative`로 라벨링 → 논조 통계 붕괴 |
| `entity-tagger` + `summarizer` | 요약 품질에 따라 `posco_relevance`가 흔들려 **카톡 발송이 불안정** |
| `issue-clusterer` + `swot-analyst` | 클러스터가 SWOT 결론에 맞춰 재구성됨 (결론 선행) |

---

---

## 8. 프롬프트 설계 원칙

### 8.1 공통

- 출력은 **JSON 강제** — 스키마 명시 + "코드펜스·설명 없이 JSON만"
- **요약은 원문 표현 재사용 금지** — 자체 문장 재작성 (저작권 + 검색 품질)
- **근거 없는 서술 금지** — 기사에 없는 배경지식 삽입 금지, 필요 시 `assumptions[]`로 분리
- 판정형 태스크는 **라벨 + 근거 문장 지목**을 함께 요구 → 사후 검증 가능
- 배치 호출 시 **입력 id를 출력에 반드시 echo** → 순서 뒤바뀜 방지 (실제로 자주 발생)
- 실패 시 부분 결과라도 반환하도록 지시, 파서는 부분 파싱 허용

### 8.2 `swot-analyst` 고정 헤더 (그대로 사용)

> 당신은 **포스코퓨처엠** 대외협력 담당자입니다. 아래 기사들이 **포스코퓨처엠에게** 무엇을 의미하는지 분석하십시오.
>
> 규칙:
> 1. **S·W는 반드시 포스코퓨처엠 내부 요인만** 기술하십시오. 경쟁사·정부·시장의 특성은 S·W에 쓸 수 없습니다.
> 2. **O·T는 외부 환경 요인만** 기술하십시오. 경쟁사의 강점은 T입니다.
> 3. 규제·정책은 자동으로 T가 아닙니다. **상대적 유불리**를 따지십시오. 규제 강화가 중국 경쟁사에 더 불리하다면 그것은 포스코퓨처엠에게 O입니다.
> 4. 각 항목에 근거 기사 id를 붙이고, 근거가 없으면 `evidence: []`, `confidence: "low"`로 표기하십시오.
> 5. 추측을 사실처럼 쓰지 마십시오. 모르면 항목을 비우십시오.
> 6. `policy_ask`는 **정부에 실제로 요청 가능한 구체적 조치**여야 합니다. "지원이 필요하다" 같은 문장은 금지입니다.

### 8.3 채널 격리

**메신저 출력 프롬프트에는 `analysis.json` / `issues.json` 컨텍스트를 아예 주입하지 않는다.** 프롬프트로 "말하지 마라"라고 지시하는 것은 방어선이 아니다. 컨텍스트에 없으면 말할 수 없다.

---
