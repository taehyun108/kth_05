// 카드 렌더 규칙 — ⚙️ 규칙요약 배지 + INV-6 (L1/L2 필드 없어도 정상 렌더)
import { test } from "node:test";
import assert from "node:assert/strict";
import { cardBadges, toCardView, RULE_SUMMARY_BADGE } from "../../lib/card.ts";

test("summary_method=extractive 이면 ⚙️ 규칙요약 배지가 붙는다", () => {
  const badges = cardBadges({ id: "x", title: "t", summary_method: "extractive", track: "posco" });
  assert.ok(badges.some((b) => b.label === RULE_SUMMARY_BADGE.label));
});

test("L1 생성요약(비-extractive)이면 규칙요약 배지가 없다", () => {
  const badges = cardBadges({ id: "x", title: "t", summary_method: "generative", track: "posco" });
  assert.ok(!badges.some((b) => b.label === RULE_SUMMARY_BADGE.label));
});

test("INV-6: tone·impact 등 L1/L2 필드가 없어도 카드가 렌더된다", () => {
  const a = { id: "l0", title: "L0 전용 기사", track: "battery", category: "cell-kr", summary: "요약", summary_method: "extractive" };
  const badges = cardBadges(a);
  // tone/impact 배지는 없지만 track·category·규칙요약 배지는 있다
  assert.ok(!badges.some((b) => b.group === "tone"));
  assert.ok(!badges.some((b) => b.group === "impact"));
  assert.ok(badges.some((b) => b.group === "track"));
  const v = toCardView(a);
  assert.equal(v.title, "L0 전용 기사");
  assert.equal(v.isExtractive, true);
  assert.ok(Array.isArray(v.bullets)); // 누락 필드는 빈 배열로 안전화
});

test("tone·impact·policy_stage 가 있으면 각각 배지가 붙는다", () => {
  const badges = cardBadges({
    id: "x", title: "t", track: "policy", category: "pol-us",
    tone: "neutral", impact: "high", policy_stage: "proposed", summary_method: "extractive",
  });
  const groups = badges.map((b) => b.group);
  assert.ok(groups.includes("tone") && groups.includes("impact") && groups.includes("policy_stage"));
});

test("제목 누락 시에도 뷰가 만들어진다", () => {
  const v = toCardView({ id: "n", title: "" });
  assert.equal(v.title, "(제목 없음)");
  assert.equal(v.href, "/posco/articles/n"); // url 없으면 상세 경로
});
