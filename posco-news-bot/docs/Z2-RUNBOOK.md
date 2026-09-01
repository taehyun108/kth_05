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
| ~~`NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET`~~ | — | **폐지.** 검색 API가 NAVER API HUB로 이관(2026-07-31 신규 신청 종료) | 쓰지 않음 |
| `NAVER_HUB_KEY_ID` / `NAVER_HUB_KEY` | (선택) 네이버 HUB 뉴스 검색 | 네이버클라우드 콘솔 — **결제수단 등록 필요** | **선택.** 비워 두면 호출조차 안 함 |
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

> **수집에 필요한 키는 없다.** 1순위 언론사 RSS·2순위 구글 뉴스 RSS 모두 키가 필요 없어서,
> `.env` 없이도 ② 스모크가 돈다. 위 표의 키는 웹·메일·L1 등 수집 이후 단계용이다.
> `SESSION_SECRET`을 안 넣으면 개발용 기본값이 쓰인다. **운영에서는 반드시 설정**할 것.
> Ollama: `ollama pull qwen2.5:7b` 등으로 후보 모델을 미리 받아 둔다.

**설치 검증**
```bash
bash ci-guard.sh                      # pytest + INV grep  → 93 passed 기대
node --test "tests/web/**/*.test.ts"  # → 44 pass 기대
python -m pipeline.stages.s1_collect --dry-run --max-queries 20   # 네트워크 없이 피드 목록·쿼리 계획만
```
- ❌ `ci-guard` 실패 → 코드/환경 불일치. 파이썬 버전·pyyaml 확인.
- ❌ 웹 테스트가 TS 파싱 에러 → **Node 22 미만**. 타입 스트리핑이 없어서다.

---

## ② 스모크 실행 (실데이터 RSS 검증)

**이 단계의 본론은 "매체마다 RSS 포맷이 다르다"를 실제로 확인하는 것이다.**
합성 피드로는 우리가 상상한 편차만 검증된다. 실제 매체는 상상 밖의 모양을 낸다.

### ②-1 먼저 `rss_sources.yaml` 을 채운다

`pipeline/rss_sources.yaml` 에는 지금 **예시 3건(모두 `verified: false`)** 만 들어 있다.
Z2에서 실제 주소를 확인해 채우고, 확인한 것만 `verified: true` 로 바꾼다.

```yaml
sources:
  - id: yonhap-economy      # 파이프라인 내부 식별자(고유). 리포트·feed_health 키
    name: 연합뉴스           # 매체명. ★커버리지 집계와 미등록 매체 후보 판정의 키★
    tier: 1                 # 1=주요 2=보조 (dedup 대표 선정 참고)
    section: economy        # 섹션 메모
    url: https://www.yna.co.kr/rss/economy.xml
    lang: ko
    enabled: true
    verified: false         # ← 실제로 열어 본 뒤 true
    source_type: news       # 관보·부처 피드는 gazette
```

RSS 주소 찾는 법: 매체 홈 → 하단 "RSS" 링크 / `<link rel="alternate" type="application/rss+xml">` 확인 /
`view-source:` 로 `rss`·`feed` 문자열 검색. **브라우저에서 XML이 보이면 그 주소가 맞다.**
매체가 RSS 목록 페이지를 두는 경우가 많다(예: 전자신문 <https://www.etnews.com/rss/> — 40개 섹션 주소가 한 페이지에 있다).

> **XML이 보이는 것만으로 끝이 아니다.** 상단 `<pubDate>`와 첫 `<item>`의 날짜를 반드시 본다.
> 전자신문 소재 피드처럼 **200을 주면서 몇 달째 갱신이 멈춘** 섹션이 실제로 있다.

- ❌ `name` 을 실제 매체 표기와 다르게 적으면 → 구글 경로로 같은 매체가 들어왔을 때 **"RSS 미등록 매체 후보"로 잘못 뜬다.** 표기를 기사에 나오는 매체명과 맞출 것.
- ❌ `id` 중복 → `feed_health.json` 이 섞여 죽은 피드 판정이 틀어진다. `test_rss_sources_yaml_schema` 가 잡는다.

### ②-2 스모크 실행

```bash
python -m scripts.smoke_collect                       # 활성 RSS 전체, 최근 24h
python -m scripts.smoke_collect --feed yonhap-economy # 피드 1개만 (새로 추가한 피드 검증)
python -m scripts.smoke_collect --with-google         # 구글 보조까지 함께
```

### 반드시 눈으로 확인할 것 — **매체별 파싱 편차 표**

리포트 한가운데의 표가 이 스모크의 본체다. 열마다 무엇을 뜻하는지:

| 열 | 무엇을 보나 | 정상 | 이상하면 |
|---|---|---|---|
| **건수** | 피드가 실제로 준 항목 수 | 매체당 10~100 | **0** → URL 오류·차단·빈 피드. 브라우저로 같은 주소를 열어 구분한다. 며칠 이어지면 S8이 "죽은 피드 의심"으로 경고 |
| **최신 기사일** | 피드의 가장 최근 `pubDate` | 오늘~며칠 이내 | **몇 주 전이면 갱신이 멈춘 피드다.** 200 이 오고 항목도 가득해서 건수로는 안 잡힌다. 실제로 전자신문 `06064.xml`(소재)이 2026-09-01 시점 **68일 정체** 상태였다. 섹션 폐지·이전 여부를 확인하고 대체 피드로 교체. 주간 갱신이 정상인 섹션이면 `rss_sources.yaml` 에 `stale_days: 30` 처럼 피드별 임계를 준다 |
| **날짜X** | `pubDate`/`dc:date`/`updated` 파싱 실패 건수 | 0 | **전량 실패면 그 매체만의 날짜 포맷**이다. 경고 줄에 찍힌 원본 샘플을 `rss.py`의 `_NAIVE_FORMATS` 에 추가. 방치하면 수집시각으로 폴백돼 **`id`(날짜+해시)와 일일 경계가 하루 밀린다** |
| **설명X** | `description` 결손 | 매체별로 0~전량 | **전량 결손은 정상일 수 있다**(제목만 주는 피드). 단 L0 추출 요약이 제목만으로 만들어지므로 요약 품질이 떨어진다 → §F-02 본문 크롤링 대상으로 표시 |
| **링크X** | `<link>` 를 못 읽은 건수 | 0 | Atom `<link href=...>`·다중 `<link rel>` 형태다. `_link_of()` 확인. 링크가 없으면 canonical·id가 만들어지지 않아 **그 매체 전체가 유실**된다 |
| **분류X** | `<category>` 결손 | 매체별 상이 | 결손 자체는 무해(필터는 제목·설명도 본다). 분류가 있으면 필터 통과율이 오른다 |
| **이상** | CDATA 마커·HTML 태그·엔티티·U+FFFD·제어문자 잔존 | **0** | >0이면 정규화 계층이 안 먹은 것. 특히 **CDATA 안에 태그가 든 매체**가 흔하다 → `rss.clean_text()` 수정. 이게 남으면 카톡 포맷 검증(`validate_body`)에서 통째로 미발송된다 |

표 아래 요약 줄도 함께 본다:

| 항목 | 정상 | 이상하면 |
|---|---|---|
| **키워드 통과 / 원본** | 원본의 5~30% | **0% 통과** → `keywords.yaml` must 가 그 매체 섹션과 안 맞는다. 섹션을 바꾸거나(경제→산업) 키워드를 넓힌다. **100% 통과**면 필터가 안 걸린 것 |
| **중복 canonical군** | 통신사 전재가 있으면 >0 | 매체를 여럿 등록했는데 0이면 dedup이 안 도는 것 |
| **RSS 미등록 매체 후보** | `--with-google` 시 표시 | 여기 뜬 매체의 피드 주소를 찾아 `rss_sources.yaml` 에 추가한다. **이 목록이 RSS 전환의 커버리지 구멍이다** |

> `originallink` / 네이버 중계링크 확인 항목은 **없어졌다.** 언론사 RSS는 원문 URL을 그대로 주므로 중계링크 자체가 발생하지 않는다.

### 산출물
- `tests/fixtures/collect_rss_<feed>.sample.json` — **커밋 대상**. 메타데이터 + **200자 이내 발췌만**(INV-5: 본문 전문 금지).
- `cache/smoke/raw-rss-*.jsonl`, `cache/smoke/smoke-report.json` — 원본. `cache/`는 `.gitignore`라 **커밋되지 않는다**.

### 실패 해석
- ❌ 전 피드 0건 + 오류도 0 → `rss_sources.yaml` 의 `enabled` 가 전부 false. 예시 3건은 `verified: false` 일 뿐 `enabled: true` 다.
- ❌ 전 피드 오류(`URLError`/timeout) → 아웃바운드 차단. 사내 프록시 환경변수(`HTTPS_PROXY`) 확인. **이 상태에서 파이프라인을 돌리면 S1이 `failed`(전 소스 실패)로 찍힌다.**
- ❌ 특정 매체만 403 → User-Agent 차단. `rss.USER_AGENT` 를 바꾸거나 그 매체는 구글 경로에 맡긴다.
- ❌ 구글 RSS만 429/403 → 비공식 엔드포인트 차단(P1-3 리스크). **RSS 1순위가 살아 있으면 파이프라인은 계속 돈다.** 미등록 매체 후보 집계만 못 하게 되므로 그동안은 수동으로 매체를 넓힌다.
- ❌ 한글이 깨져 보임(U+FFFD) → 그 매체가 EUC-KR 이다. XML 선언의 `encoding` 을 확인하고 필요하면 디코딩 경로를 손본다.

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
