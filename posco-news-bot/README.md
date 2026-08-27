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
  keywords.yaml        T1~T4 키워드 + posco_entities (카톡 게이트 사전)
  dispatch_routes.yaml 발송 라우팅
tests/test_invariants.py  INV 자동 검증
ci-guard.sh       INV grep 검사 + 테스트 실행
```

## 검증

```bash
bash ci-guard.sh
```

## 착수 전 확인

- [ ] 카카오 오픈채팅 API 사용 신청 (승인 전엔 `dispatch_routes.yaml` → `kakao-team.enabled: false`)
- [ ] 국가법령정보센터 Open API 인증키
- [ ] `keywords.yaml` 의 `posco_entities`·`futurem_products` 검토 — **카톡 발송 게이트의 근거**
- [ ] Vercel 플랜 및 내부 분석자료 외부 저장 정책 (docs/11-decisions.md P0-7)
- [ ] Ollama 한국어 요약 품질 실측 (docs/11-decisions.md P0-5)
