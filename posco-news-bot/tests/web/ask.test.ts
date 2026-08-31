// P8 Q&A 챗봇 — 채널 스코프 게이트 + 근거 강제.
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { ask, resolveScope, extractSlots, retrieve } from "../../lib/ask.ts";
import type { Article } from "../../lib/ask.ts";
import { askResponse } from "../../lib/api.ts";

const FIX = path.join(path.dirname(fileURLToPath(import.meta.url)), "fixtures");

const CORPUS: Article[] = [
  { id: "a1", title: "포스코퓨처엠 양극재 증설", summary: "포스코퓨처엠 광양 증설.",
    date: "2026-08-27", track: "posco", tone: "positive", posco_relevance: "primary",
    facets: ["track:posco", "company:futurem", "topic:양극재"] },
  { id: "a2", title: "CATL 나트륨이온 양산", summary: "CATL 나트륨이온 저가 공세.",
    date: "2026-08-27", track: "battery", tone: "neutral", posco_relevance: "none",
    facets: ["track:battery", "company:CATL", "topic:나트륨이온"] },
];
const ISSUES = [{
  issue_id: "iss-1", title: "북미거점반사이익", status: "open",
  swot: { S: [{ text: "북미거점반사이익 역량" }], W: [], O: [], T: [] },
}];


// ── 스코프 게이트 ────────────────────────────────────────────────────────────

test("resolveScope: issues 는 web+L2 에서만, 메신저는 절대 불가", () => {
  assert.equal(resolveScope("web", "L2").includeIssues, true);
  assert.equal(resolveScope("web", "L1").includeIssues, false);
  assert.equal(resolveScope("web", null).includeIssues, false);
  assert.equal(resolveScope("telegram", "L2").includeIssues, false); // 메신저는 L2여도 불가
  assert.equal(resolveScope("kakao", "L2").includeIssues, false);
  assert.equal(resolveScope("kakao", "L2").poscoOnly, true);
});


// ── 완료기준: 텔레그램 응답에 SWOT·시사점 문자열 부재 ───────────────────────

test("텔레그램 세션은 issues 를 넘겨도 SWOT 이 컨텍스트에 들어가지 않는다", () => {
  const ans = ask({ question: "북미거점반사이익 알려줘", channel: "telegram", level: "L2",
                    articles: CORPUS, issues: ISSUES });
  // issues 를 넘겼지만 스코프가 막아 검색 대상에 없음 → 근거 없음
  assert.equal(ans.grounded, false);
  assert.equal(ans.answer, "수집된 기사에 없습니다.");
  for (const t of ["swot", "시사점", "북미거점반사이익"]) {
    assert.ok(!ans.answer.toLowerCase().includes(t), `텔레그램 응답에 ${t} 누출`);
  }
});


// ── 완료기준: 아카이브 밖 질문에 추측하지 않음 ──────────────────────────────

test("아카이브에 없는 질문 → '수집된 기사에 없습니다'", () => {
  const ans = ask({ question: "전고체 배터리 화재 사고", channel: "web", level: "L1", articles: CORPUS });
  assert.equal(ans.grounded, false);
  assert.equal(ans.answer, "수집된 기사에 없습니다.");
});

test("근거 있으면 기사 id 각주가 붙는다", () => {
  const ans = ask({ question: "포스코퓨처엠 양극재", channel: "web", level: "L1", articles: CORPUS });
  assert.equal(ans.grounded, true);
  assert.ok(ans.answer.includes("[a1]"));       // 각주
  assert.deepEqual(ans.citations, ["a1"]);
});


// ── 완료기준: L1 세션이 /api/ask 로 L2 데이터를 우회 조회 불가 ──────────────

test("L2 웹은 issues 검색 성공, L1 은 동일 질문에 근거 없음(우회 불가)", () => {
  const q = "북미거점반사이익";
  const l2 = askResponse(q, "L2", FIX);   // issues 로드 → 검색됨
  assert.equal((l2.body as { grounded: boolean }).grounded, true);
  assert.ok((l2.body as { answer: string }).answer.includes("fx-issue-1"));

  const l1 = askResponse(q, "L1", FIX);   // issues 미로드 → 근거 없음
  assert.equal((l1.body as { grounded: boolean }).grounded, false);
  assert.equal((l1.body as { answer: string }).answer, "수집된 기사에 없습니다.");
});


// ── 카톡: 포스코 관련만 ──────────────────────────────────────────────────────

test("카톡 채널은 포스코 미언급 기사를 검색 대상에서 제외", () => {
  const ans = ask({ question: "CATL 나트륨이온", channel: "kakao", level: "L1", articles: CORPUS });
  assert.equal(ans.grounded, false);            // a2(none) 제외 → 근거 없음
});


// ── 법령: 키 없으면 미지원 + 법률자문 아님 고지 ─────────────────────────────

test("법령 질의는 키 없으면 미지원 + 법률자문 아님 고지", () => {
  const ans = ask({ question: "폐기물관리법 배터리 재활용 조항 찾아줘", channel: "web", level: "L2",
                    articles: CORPUS, hasLawKey: false });
  assert.equal(ans.grounded, false);
  assert.ok(ans.answer.includes("미지원"));
  assert.ok(ans.answer.includes("법률 자문이 아니"));
});


// ── 슬롯 추출 ────────────────────────────────────────────────────────────────

test("슬롯 추출: 기간·회사·논조", () => {
  const s = extractSlots("이번 주 포스코퓨처엠 부정 기사");
  assert.equal(s.days, 7);
  assert.ok(s.companies.includes("futurem"));
  assert.ok(s.tones.includes("negative"));
});
