# Z2 RUNBOOK — 외부망 PC 실행 지침

이 문서는 **Z2(외부망 PC)에서 직접 실행할 순서**다. 개발 샌드박스는 아웃바운드가 막혀 있어
수집·크롤링·Ollama는 여기서만 실제로 돈다. 진행 상태는 `STATUS.md` 참조.

각 단계에 **"실패하면 무엇을 뜻하는지"** 를 붙여 뒀다. 증상으로 원인을 좁히는 용도다.

---

## ① 환경 준비

```bash
git clone <repo> && cd posco-news-bot
git checkout claude/project-structure-analysis-lwl00r
python -V        # 3.11+
node -v          # 22+ (웹 테스트가 TS 타입 스트리핑을 쓴다)
pip install pyyaml pytest
cp .env.example .env    # 아래 항목을 채운다
```

### `.env` 항목과 발급처

| 키 | 용도 | 발급처 / 값 | 언제 필요 |
|---|---|---|---|
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | 국내 기사 수집 | <https://developers.naver.com/apps> → 애플리케이션 등록 → **검색** API 추가 | **② 스모크부터** |
| `OLLAMA_ENDPOINT` | 로컬 LLM 주소 | 기본 `http://localhost:11434` | ④ A/B |
| `OLLAMA_MODEL` | L1 모델명 | A/B로 확정 (예: `qwen2.5:7b`) | ⑤ 확정 후 |
| `SESSION_SECRET` | 웹 세션 서명 | 임의 난수 32바이트 이상. **인스턴스 전체가 같은 값** | 웹 배포 |
| `ALLOWED_EMAIL_DOMAINS` | L1 도메인 화이트리스트 | 예 `poscofuturem.com` | 웹 배포 |
| `L2_ADMIN_EMAILS` | L2(SWOT) 허용목록 | 쉼표구분 이메일 | 웹 배포 |
| `KV_REST_API_URL` / `KV_REST_API_TOKEN` | 로그인 코드 저장소 | Vercel KV(Upstash) 대시보드 | 웹 운영 |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` | 메일 발송 | 사내 릴레이 우선, 없으면 Gmail 앱 비밀번호 | 메일 발송 |
| `MAIL_TO_GROUP` | 수신 배포 리스트 **주소 1개** | 사내 그룹 주소 | 메일 발송 |
| `KAKAO_OPENLINK_ID` | 오픈채팅방 id | 카카오 API 승인 후 발급 | 카톡 승인 후 |
| `LAW_API_KEY` | 국가법령정보센터 | <https://open.law.go.kr> 인증키 신청 | P5d |
| `TG_CHAT_POSCO` 등 | 텔레그램 채널 | BotFather + 채널 id | 텔레그램 |

> `SESSION_SECRET`을 안 넣으면 개발용 기본값이 쓰인다. **운영에서는 반드시 설정**할 것.
> Ollama: `ollama pull qwen2.5:7b` 등으로 후보 모델을 미리 받아 둔다.

**설치 검증**
```bash
bash ci-guard.sh                      # pytest + INV grep  → 93 passed 기대
node --test "tests/web/**/*.test.ts"  # → 44 pass 기대
python -m pipeline.stages.s1_collect --dry-run --max-queries 20   # 네트워크 없이 계획만
```
- ❌ `ci-guard` 실패 → 코드/환경 불일치. 파이썬 버전·pyyaml 확인.
- ❌ 웹 테스트가 TS 파싱 에러 → **Node 22 미만**. 타입 스트리핑이 없어서다.

---

## ② 스모크 실행 (실데이터 응답 검증)

합성 fixture로는 못 잡는 **실제 네이버/구글 응답의 필드 매핑·인코딩·페이징**을 확인한다.

```bash
python -m scripts.smoke_collect                       # posco/futurem, 최근 24h
# 옵션: --track battery --category cell-kr --hours 48 --no-naver --max-queries N
```

### 반드시 눈으로 확인할 것

| 항목 | 무엇을 보나 | 정상 | 이상하면 |
|---|---|---|---|
| **제목의 `<b>` 태그·`&quot;`** | 네이버 검색 API는 검색어를 `<b>`로 감싸고 HTML 엔티티를 그대로 준다 | fixture의 `title`에 `<b>`·`&quot;`·`&amp;`가 **없어야** 함 | 남아 있으면 `s1_collect._clean()`(태그 제거+`html.unescape`)이 안 먹은 것 → 파서 수정 |
| **pubDate 타임존** | 네이버는 RFC822(`+0900`), 구글 RSS는 GMT | `published_at`이 **+09:00 KST**로 변환돼 있어야 함 | UTC로 남아 있으면 날짜가 하루 밀려 `id`(날짜+해시)와 일일 경계가 틀어진다 → `parsedate_to_datetime(...).astimezone(KST)` 확인 |
| **`originallink` vs `link`** | 네이버 `link`는 news.naver.com 중계, `originallink`가 언론사 원문 | `url`이 **언론사 도메인**이어야 함(카톡 카드·메일 링크가 원문이어야 INV-9) | 전부 naver.com이면 `originallink` 누락 → 폴백 로직 확인. dedup도 원문 기준이라 중복 병합률이 떨어진다 |
| 필드 누락 | 리포트의 `필드 누락` 표 | `title`/`url`/`published_at` 결손 0 | 결손이 있으면 해당 소스 파서 수정 |
| 인코딩 이상 | `U+FFFD`·미복원 엔티티·제어문자·NFC 불일치 | 0건 | >0이면 디코딩 경로 문제(한글 깨짐) |
| 페이징 | 수집 건수가 `display` 상한에 딱 걸리는지 | 100에 정확히 걸리면 페이징 필요 | 상한 포화면 `start` 파라미터 페이징 추가 검토 |

### 산출물
- `tests/fixtures/collect_<track>_<category>.sample.json` — **커밋 대상**. 메타데이터 + **200자 이내 발췌만**(INV-5: 본문 전문 금지).
- `cache/smoke/raw-*.jsonl` — 원본. `cache/`는 `.gitignore`라 **커밋되지 않는다**.

### 실패 해석
- ❌ `NAVER_CLIENT_ID/SECRET 미설정` 경고만 뜨고 구글만 수집 → `.env` 미로드. 실행 위치가 리포 루트인지 확인.
- ❌ 구글 RSS만 401/403/429 → 비공식 엔드포인트 차단(P1-3 리스크). 네이버로 폴백하고 해외분 손실을 감수, 중장기 개별 매체 RSS 등록.
- ❌ 네이버 401 → 키 오타 또는 **검색 API 미추가**(앱에 "검색"을 붙여야 한다).
- ❌ 수집 0건인데 오류도 0 → 키워드가 24h 내 결과가 없는 것. `--hours 72`로 넓혀 재확인.

---

## ③ fixture 확보 (A/B용 실기사 20건)

P0-5 A/B는 **본문(body)** 이 필요하다. 본문 전문은 **git에 커밋하면 안 된다(INV-5)**.

```bash
mkdir -p cache/z2                     # cache/ 는 .gitignore → 안전
$EDITOR cache/z2/articles20.jsonl
```

한 줄에 한 건, 형식:
```json
{"id":"2026-09-01-aaaaaaaaaa","title":"기사 제목","outlet":"연합뉴스","body":"기사 본문 전문..."}
```

- 20건은 **트랙을 섞어서**(포스코 8 / 배터리 6 / 정책 3 / 통상 3 정도) 고른다. 포스코 언급 기사가 절반 이상이어야 카톡 포맷(포스코 언급 필수) 검증이 된다.
- 스모크 fixture(`tests/fixtures/*.sample.json`)에는 발췌만 있어 A/B에 못 쓴다. **본문은 원문 페이지에서 직접** 넣는다.

- ❌ 실수로 `tests/fixtures/`나 `data/`에 본문을 넣으면 INV-5 위반. 반드시 `cache/z2/`.

---

## ④ P0-5 A/B 실행 (L1 모델 선정)

```bash
ollama list                                   # 후보 모델이 받아져 있는지
python -m scripts.ab_summarize \
  --input cache/z2/articles20.jsonl \
  --models "qwen2.5:7b,gemma2:9b,exaone3.5:7.8b"
```

산출: `results/p0-5/ab-<타임스탬프>.md` / `.csv` (`results/`는 `.gitignore`).

### 결과 해석

**(1) 자동 지표 — 모델별 집계표**
- `포맷 통과율` = `validate_kakao` 본문 규칙 통과 비율. **여기가 낮으면 카톡에 못 나간다.**
  - 흔한 실패: 존댓말 종결 아님(`~했다.`), 분량 이탈(150~350자), `[매체명] ` 머리말 누락, 포스코 언급 없음, 이모지/URL 혼입.
  - 통과율이 모델 문제인지 프롬프트 문제인지는 **실패 사유 분포**로 갈린다. 전 모델이 같은 사유로 깨지면 → 프롬프트(`s4_l1.PROMPT_TEMPLATE`) 수정. 특정 모델만 깨지면 → 그 모델 탈락.
- `평균길이`/`평균문장`: 150~350자·3~5문장 근처여야 한다.

**(2) 사람 채점 — 상세표의 빈 칸을 채운다**
- `사실오류(Y/N)`: **원문에 없는 내용**이 있으면 Y.
- `자연스러움(1-5)`.

**(3) 판정 기준 (docs/11-decisions.md P0-5)**
- **사실오류 2건 이상 → 그 모델 탈락.** 아카이브 신뢰도가 먼저다.
- 통과 모델 중 자연스러움 평균이 가장 높은 것을 채택.
- **전부 미달이면 L1을 쓰지 않는다.** L0 추출 요약을 유지하고 카톡은 계속 스킵(INV-6). 억지로 생성요약을 쓰지 않는다.

### 실패 해석
- ❌ 전 모델 `가용 ❌` → Ollama 미기동. `ollama serve` 또는 `OLLAMA_ENDPOINT` 확인.
- ❌ 통과율 0인데 요약은 그럴듯함 → 포맷 규칙 위반. `.md`의 `format_errs` 열을 보고 프롬프트 보강.
- ❌ 소요시간이 건당 수십 초 → GPU 미사용(CPU 추론). 야간 배치로 돌리거나 더 작은 모델.

---

## ⑤ 모델 확정 후 할 일

1. `.env`에 `OLLAMA_MODEL=<확정 모델>` 고정.
2. 전 구간 확인 (합성):
   ```bash
   python -m scripts.rehearsal          # S0~S8 완주 · 카톡 대상·L0-only 비교
   ```
3. 실데이터 1회전 (발송 없이):
   ```bash
   python pipeline/orchestrator.py --mode daily --dry-run
   ```
   - `S4L1`이 `skipped`가 아니라 `success (ok: N)`이면 L1이 붙은 것.
   - `S7`이 `skipped(발송 차단)` — dry-run이라 정상.
4. 카톡 대상이 **포스코 언급분만**인지 리포트에서 확인. 아니면 `posco_relevance` 사전(`keywords.yaml`)을 손본다.
5. **섀도 운영**: `dispatch_routes.yaml`의 `shadow_to_env`로 담당자 개인 채널에만 1~2주 보낸 뒤 단체방 전환. 승인 전까지 `kakao-team.enabled: false` 유지.
6. 메일은 SMTP 채우고 **1주 본인 → 2주 팀원 → 3주 배포 리스트** 순으로 올린다(스팸 학습 방지, P0-6).

### 되돌아가야 하는 신호
- 카톡에 **포스코 미언급 기사가 나갔다** → 즉시 `enabled: false`. `posco_relevance` 판정 로그 감사.
- `tone=crisis`가 자동 발송됨 → `hold_on_crisis` 가드 확인. crisis는 사람 승인이 원칙.
- L1 요약에 원문에 없는 내용 → 모델 교체 또는 L0 복귀. **틀린 요약보다 요약 없는 게 낫다.**
