// 세션 서명/검증 — 위·변조 거부, 만료
import { test } from "node:test";
import assert from "node:assert/strict";
import { signSession, verifySession, readClaims } from "../../lib/session.ts";

const KEY = "test-key";

test("서명→검증 왕복", () => {
  const t = signSession({ email: "a@poscofuturem.com", level: "L1" }, { key: KEY, now: 1000, ttlMs: 10000 });
  const p = verifySession(t, { key: KEY, now: 2000 });
  assert.equal(p?.email, "a@poscofuturem.com");
  assert.equal(p?.level, "L1");
});

test("서명 변조 시 null", () => {
  const t = signSession({ email: "a", level: "L2" }, { key: KEY });
  assert.equal(verifySession(t.slice(0, -2) + "xx", { key: KEY }), null);
});

test("다른 키로는 검증 실패", () => {
  const t = signSession({ email: "a", level: "L2" }, { key: KEY });
  assert.equal(verifySession(t, { key: "other" }), null);
});

test("만료된 세션은 null", () => {
  const t = signSession({ email: "a", level: "L1" }, { key: KEY, now: 1000, ttlMs: 100 });
  assert.equal(verifySession(t, { key: KEY, now: 5000 }), null);
});

test("readClaims: 서명 무시하고 만료만 (Edge middleware 용)", () => {
  const t = signSession({ email: "a", level: "L1" }, { key: KEY, now: 1000, ttlMs: 100 });
  assert.ok(readClaims(t, 1050));       // 만료 전 → 클레임 반환
  assert.equal(readClaims(t, 5000), null); // 만료 후 → null
  assert.equal(readClaims(null), null);
});
