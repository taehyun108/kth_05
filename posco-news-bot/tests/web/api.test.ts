// P3 완료기준 ① L1 세션 /api/issues → 403,  ② /api/articles 응답에 L2 필드 부재
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  articlesResponse, issuesResponse, analysisResponse, weeklyResponse,
  policiesResponse, disputesResponse,
} from "../../lib/api.ts";
import { L2_ONLY, filterArticlesForLevel } from "../../lib/fields.ts";

const FIX = path.join(path.dirname(fileURLToPath(import.meta.url)), "fixtures");

test("완료기준②: /api/articles L1 응답에 L2 필드가 아예 없다", () => {
  const res = articlesResponse("L1", FIX);
  assert.equal(res.status, 200);
  const arts = res.body.articles as Record<string, unknown>[];
  assert.equal(arts.length, 1);
  for (const a of arts) {
    for (const f of L2_ONLY) {
      assert.ok(!(f in a), `L1 응답에 L2 필드 '${f}' 가 남아있으면 안 됨`);
    }
  }
});

test("L2 세션은 L2 필드를 그대로 받는다", () => {
  const res = articlesResponse("L2", FIX);
  const a = (res.body.articles as Record<string, unknown>[])[0];
  assert.equal(a.futurem_implication, "L2 전용 — L1 응답에서 제거돼야 함");
  assert.ok("body" in a);
});

test("완료기준①: L1 세션으로 /api/issues 호출 시 403", () => {
  assert.equal(issuesResponse("L1", FIX).status, 403);
});

test("미인증(null) 은 401, L2 는 200", () => {
  assert.equal(issuesResponse(null, FIX).status, 401);
  assert.equal(issuesResponse("L2", FIX).status, 200);
  assert.equal(articlesResponse(null, FIX).status, 401);
});

test("/api/analysis 도 L2 전용 (L1 → 403)", () => {
  assert.equal(analysisResponse("L1", FIX).status, 403);
});

test("완료기준: /api/weekly 도 L2 전용 (L1 → 403, 미인증 → 401, L2 → 200)", () => {
  assert.equal(weeklyResponse("L1", FIX).status, 403);
  assert.equal(weeklyResponse(null, FIX).status, 401);
  assert.equal(weeklyResponse("L2", FIX).status, 200);
});

test("완료기준: /api/policies L1 응답에 our_position·policy_ask 부재(board), L2엔 존재(full)", () => {
  assert.equal(policiesResponse(null, FIX).status, 401);
  const l1 = policiesResponse("L1", FIX);
  assert.equal(l1.status, 200);
  const p1 = (l1.body.policies as Record<string, unknown>[])[0];
  assert.ok(!("our_position" in p1) && !("policy_ask" in p1), "L1 board에 민감 필드 누출");
  const l2 = policiesResponse("L2", FIX);
  const p2 = (l2.body.policies as Record<string, unknown>[])[0];
  assert.equal(p2.our_position, "음극재 포함 요청");   // L2 full 엔 존재
});

test("완료기준: /api/disputes L1 board엔 affects/products 부재, L2 full엔 존재", () => {
  const d1 = (disputesResponse("L1", FIX).body.disputes as Record<string, unknown>[])[0];
  assert.ok(!("affects_futurem" in d1) && !("products" in d1), "L1 board에 affects 누출");
  const d2 = (disputesResponse("L2", FIX).body.disputes as Record<string, unknown>[])[0];
  assert.equal(d2.affects_futurem, true);
});

test("filterArticlesForLevel 은 원본을 변형하지 않는다(L1 사본만 제거)", () => {
  const src = [{ id: "x", body: "secret", swot_axis: "T", title: "t" }];
  const out = filterArticlesForLevel(src, "L1");
  assert.ok(!("body" in out[0]) && !("swot_axis" in out[0]));
  assert.equal(src[0].body, "secret"); // 원본 보존
});
