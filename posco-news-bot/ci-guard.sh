#!/usr/bin/env bash
# INV grep 검사 — 테스트로 못 잡는 정적 위반을 걸러낸다
set -e

if grep -rn "issues\.json\|analysis\.json\|weekly\.json\|policy_ask\|futurem_implication\|swot" \
     pipeline/stages/s7_dispatch.py pipeline/stages/s7_mail.py bot/ 2>/dev/null; then
  echo "❌ INV-3/7 위반: 발송·메일 경로에서 비공개 분석 데이터 참조"; exit 1
fi

if ls public/*.json public/data 2>/dev/null | grep -q .; then
  echo "❌ INV-5/8 위반: public/ 에 데이터 파일 존재 — 인증 없이 서빙됨"; exit 1
fi

if git ls-files --error-unmatch cache/ >/dev/null 2>&1; then
  echo "❌ INV-5 위반: cache/ 가 git에 추적되고 있음"; exit 1
fi

python3 -m pytest tests/ -q
echo "✅ INV 검사 통과"
