// API 코어 — 세션 레벨로 데이터/필드를 서버에서 걸러 응답 (INV-8).
// Next 비의존: route.ts 가 이 결과를 NextResponse 로 감싼다. 테스트는 여기를 직접 호출.
import type { Level } from "./levels.ts";
import { requireLevel } from "./guard.ts";
import { filterArticlesForLevel } from "./fields.ts";
import { readDataFile } from "./data.ts";

export interface ApiResult {
  status: number;
  body: Record<string, unknown>;
}

// /api/articles — L1 이상. L1 응답에는 L2 필드가 없다.
export function articlesResponse(level: Level | null | undefined, dir?: string): ApiResult {
  const g = requireLevel(level, "L1");
  if (!g.ok) return { status: g.status, body: { error: g.status === 401 ? "unauthorized" : "forbidden" } };
  const raw = readDataFile("articles", dir);
  const articles = filterArticlesForLevel((raw.articles as Record<string, unknown>[]) || [], level as Level);
  return { status: 200, body: { ...raw, articles } };
}

// /api/issues — L2 전용 (SWOT). L1 세션은 403.
export function issuesResponse(level: Level | null | undefined, dir?: string): ApiResult {
  const g = requireLevel(level, "L2");
  if (!g.ok) return { status: g.status, body: { error: g.status === 401 ? "unauthorized" : "forbidden" } };
  const raw = readDataFile("issues", dir);
  return { status: 200, body: raw };
}

// /api/analysis — L2 전용 (시사점·swot_axis).
export function analysisResponse(level: Level | null | undefined, dir?: string): ApiResult {
  const g = requireLevel(level, "L2");
  if (!g.ok) return { status: g.status, body: { error: g.status === 401 ? "unauthorized" : "forbidden" } };
  const raw = readDataFile("analysis", dir);
  return { status: 200, body: raw };
}

// /api/weekly — L2 전용 (주간 브리프·outlook). likely·monitoring 은 웹에서만.
export function weeklyResponse(level: Level | null | undefined, dir?: string): ApiResult {
  const g = requireLevel(level, "L2");
  if (!g.ok) return { status: g.status, body: { error: g.status === 401 ? "unauthorized" : "forbidden" } };
  const raw = readDataFile("weekly", dir);
  return { status: 200, body: raw };
}

// /api/policies — L1 이상. ★L1은 board 축약본(our_position·policy_ask 없음), L2는 full★
export function policiesResponse(level: Level | null | undefined, dir?: string): ApiResult {
  const g = requireLevel(level, "L1");
  if (!g.ok) return { status: g.status, body: { error: g.status === 401 ? "unauthorized" : "forbidden" } };
  const raw = readDataFile(level === "L2" ? "policies" : "policy_board", dir);
  return { status: 200, body: raw };
}

// /api/disputes — L1 이상. L1은 board 축약본, L2는 full(affects·products 포함).
export function disputesResponse(level: Level | null | undefined, dir?: string): ApiResult {
  const g = requireLevel(level, "L1");
  if (!g.ok) return { status: g.status, body: { error: g.status === 401 ? "unauthorized" : "forbidden" } };
  const raw = readDataFile(level === "L2" ? "disputes" : "dispute_board", dir);
  return { status: 200, body: raw };
}
