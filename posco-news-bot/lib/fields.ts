// 응답 필드 필터링 (docs/05-auth.md §4.12.4, INV-8)
//   L1 에게는 L2 필드를 ★응답에 담지 않는다★. 숨기는 게 아니라 아예 없어야 한다.
import type { Level } from "./levels.ts";

// L2 전용 비공개 필드 — L1 응답에서 제거 (s4_analyze.FORBIDDEN_OUT 와 동일 집합)
export const L2_ONLY = [
  "futurem_implication",
  "swot_axis",
  "sector_impact",
  "frame",
  "tone_evidence",
  "policy_ask_hint",
  "fact_check_flags",
  "body",
];

export function omitFields<T extends Record<string, unknown>>(obj: T, keys: string[]): T {
  const out = { ...obj };
  for (const k of keys) delete (out as Record<string, unknown>)[k];
  return out;
}

export function filterArticleForLevel(article: Record<string, unknown>, level: Level): Record<string, unknown> {
  return level === "L2" ? article : omitFields(article, L2_ONLY);
}

export function filterArticlesForLevel(articles: Record<string, unknown>[], level: Level): Record<string, unknown>[] {
  return (articles || []).map((a) => filterArticleForLevel(a, level));
}
