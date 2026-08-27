// 완료기준 ④ 링크→로그인→원래 기사 복귀 (next 안전 처리) + 레벨 게이트
import { test } from "node:test";
import assert from "node:assert/strict";
import { requireLevel, safeNext, loginRedirect } from "../../lib/guard.ts";

test("requireLevel: 레벨 게이트", () => {
  assert.equal(requireLevel("L2", "L2").status, 200);
  assert.equal(requireLevel("L1", "L2").status, 403); // 인증O 권한X
  assert.equal(requireLevel(null, "L2").status, 401); // 미인증
  assert.equal(requireLevel("L1", "L1").status, 200);
});

test("완료기준④: next 는 자체 경로만 허용 (오픈 리다이렉트 방지)", () => {
  assert.equal(safeNext("/posco/articles/abc"), "/posco/articles/abc"); // 정상 복귀
  assert.equal(safeNext("https://evil.com"), "/posco/"); // 절대 URL 차단
  assert.equal(safeNext("//evil.com"), "/posco/"); // 프로토콜 상대 차단
  assert.equal(safeNext("/\\evil.com"), "/posco/"); // 백슬래시 차단
  assert.equal(safeNext("javascript:alert(1)"), "/posco/"); // 스킴 차단
  assert.equal(safeNext(null), "/posco/");
  assert.equal(safeNext("/policy/?country=US"), "/policy/?country=US"); // 쿼리 보존
});

test("loginRedirect 는 next 를 인코딩해 붙인다", () => {
  assert.equal(loginRedirect("/posco/articles/x"), "/login?next=%2Fposco%2Farticles%2Fx");
  assert.equal(loginRedirect("https://evil.com"), "/login?next=%2Fposco%2F");
});
