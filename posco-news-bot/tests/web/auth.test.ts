// 로그인 코드 수명주기 — 만료·5회·일회성·논스·발급제한·레벨
import { test } from "node:test";
import assert from "node:assert/strict";
import { requestCode, verifyCode, createMemoryStore, MAX_ATTEMPTS } from "../../lib/auth.ts";

const DOMAIN = "poscofuturem.com";
process.env.ALLOWED_EMAIL_DOMAINS = DOMAIN;
process.env.L2_ADMIN_EMAILS = "admin@poscofuturem.com";

test("정상 흐름: 발급 → 검증 성공, 레벨 부여", () => {
  const store = createMemoryStore();
  const r = requestCode("user@poscofuturem.com", { store, now: 0, code: "123456", nonce: "N1" });
  assert.equal(r.ok, true);
  assert.equal(r.level, "L1");
  const v = verifyCode("user@poscofuturem.com", "123456", "N1", { store, now: 1000 });
  assert.equal(v.ok, true);
  assert.equal(v.level, "L1");
});

test("허용목록 이메일은 L2", () => {
  const store = createMemoryStore();
  const r = requestCode("admin@poscofuturem.com", { store, now: 0, code: "111111", nonce: "N" });
  assert.equal(r.level, "L2");
});

test("도메인 밖 이메일은 발급 거부", () => {
  const store = createMemoryStore();
  const r = requestCode("outsider@gmail.com", { store, now: 0 });
  assert.equal(r.ok, false);
  assert.equal(r.reason, "email_not_allowed");
});

test("만료된 코드 거부", () => {
  const store = createMemoryStore();
  requestCode("u@poscofuturem.com", { store, now: 0, code: "222222", nonce: "N" });
  const v = verifyCode("u@poscofuturem.com", "222222", "N", { store, now: 11 * 60 * 1000 });
  assert.equal(v.ok, false);
  assert.equal(v.reason, "expired");
});

test("일회성: 한 번 성공하면 재사용 불가", () => {
  const store = createMemoryStore();
  requestCode("u@poscofuturem.com", { store, now: 0, code: "333333", nonce: "N" });
  assert.equal(verifyCode("u@poscofuturem.com", "333333", "N", { store, now: 1 }).ok, true);
  const again = verifyCode("u@poscofuturem.com", "333333", "N", { store, now: 2 });
  assert.equal(again.ok, false);
  assert.equal(again.reason, "no_code");
});

test("논스 불일치 거부 (세션 고정 방지)", () => {
  const store = createMemoryStore();
  requestCode("u@poscofuturem.com", { store, now: 0, code: "444444", nonce: "GOOD" });
  const v = verifyCode("u@poscofuturem.com", "444444", "BAD", { store, now: 1 });
  assert.equal(v.ok, false);
  assert.equal(v.reason, "nonce_mismatch");
});

test("5회 실패 시 코드 폐기", () => {
  const store = createMemoryStore();
  requestCode("u@poscofuturem.com", { store, now: 0, code: "555555", nonce: "N" });
  for (let i = 0; i < MAX_ATTEMPTS - 1; i++) {
    assert.equal(verifyCode("u@poscofuturem.com", "000000", "N", { store, now: 1 }).reason, "wrong_code");
  }
  const last = verifyCode("u@poscofuturem.com", "000000", "N", { store, now: 1 });
  assert.equal(last.reason, "too_many_attempts");
  // 폐기 후 정답 코드도 무효
  assert.equal(verifyCode("u@poscofuturem.com", "555555", "N", { store, now: 1 }).reason, "no_code");
});

test("발급 제한: 5분 내 3회 초과 거부", () => {
  const store = createMemoryStore();
  for (let i = 0; i < 3; i++) {
    assert.equal(requestCode("u@poscofuturem.com", { store, now: i }).ok, true);
  }
  const r = requestCode("u@poscofuturem.com", { store, now: 4 });
  assert.equal(r.ok, false);
  assert.equal(r.reason, "rate_limited");
});
