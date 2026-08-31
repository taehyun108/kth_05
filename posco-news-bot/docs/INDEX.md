# docs 색인

작업 유형별로 **필요한 문서만** 읽는다. 전부 읽지 말 것.

| 하려는 작업 | 읽을 문서 |
|---|---|
| **지금 어디까지 됐나 / 다음 할 일** | `../STATUS.md` ← **먼저 읽기** |
| **Z2 외부망 PC에서 실행** | `Z2-RUNBOOK.md` |
| 처음 파악 | `00-overview.md` → `ROADMAP.md` |
| 수집기 구현 | `01-collect.md` + `10-data-model.md` |
| 요약·분석 구현 | `02-analyze.md` + `09-orchestrator.md`(에이전트 절) |
| SWOT·법령·주간 | `03-swot-law.md` |
| 웹 화면 | `04-frontend.md` + `10-data-model.md` |
| 로그인·API 권한 | `05-auth.md` |
| **카톡·텔레그램 발송** | `06-dispatch.md` ← 🔒 포맷 고정 명세 |
| 메일 | `07-mail.md` |
| 챗봇 | `08-chatbot.md` |
| 파이프라인 실행 구조 | `09-orchestrator.md` |
| 스키마 확인 | `10-data-model.md` |
| 왜 이렇게 정했는지 | `11-decisions.md`, `12-verification-history.md` |

## 읽기 규칙

- `CLAUDE.md`는 항상 로드된다. **불변 규칙(INV)과 금지 목록은 거기 있다.**
- `12-verification-history.md`는 구현 중 읽지 않는다. 이미 반영된 결함 이력이다. **되돌리지 말 것.**
- 문서와 코드가 충돌하면 **문서가 기준**이다. 코드를 고치되, INV와 충돌하면 멈추고 물어볼 것.
