// 로그인 코드 수명주기 — 만료·5회·일회성·논스·발급제한·레벨 (KV 백엔드)
import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { requestCode, verifyCode, MAX_ATTEMPTS } from "../../lib/auth.ts";
import { createMemoryKV } from "../../lib/kvstore.ts";

// env 를 테스트 단위로 설정·복원해 전역 상태를 남기지 않는다(격리)
const _saved: Record<string, string | undefined> = {};
beforeEach(() => {
  _saved.ALLOWED_EMAIL_DOMAINS = process.env.ALLOWED_EMAIL_DOMAINS;
  _saved.L2_ADMIN_EMAILS = process.env.L2_ADMIN_EMAILS;
  process.env.ALLOWED_EMAIL_DOMAINS = "poscofuturem.com";
  process.env.L2_ADMIN_EMAILS = "admin@poscofuturem.com";
});
afterEach(() => {
  for (const k of ["ALLOWED_EMAIL_DOMAINS", "L2_ADMIN_EMAILS"]) {
    if (_saved[k] === undefined) delete process.env[k];
    else process.env[k] = _saved[k];
  }
});

test("정상 흐름: 발급 → 검증 성공, 레벨 부여", async () => {
  const kv = createMemoryKV();
  const r = await requestCode("user@poscofuturem.com", { kv, now: 0, code: "123456", nonce: "N1" });
  assert.equal(r.ok, true);
  assert.equal(r.level, "L1");
  const v = await verifyCode("user@poscofuturem.com", "123456", "N1", { kv, now: 1000 });
  assert.equal(v.ok, true);
  assert.equal(v.level, "L1");
});

test("허용목록 이메일은 L2", async () => {
  const kv = createMemoryKV();
  const r = await requestCode("admin@poscofuturem.com", { kv, now: 0, code: "111111", nonce: "N" });
  assert.equal(r.level, "L2");
});

test("도메인 밖 이메일은 발급 거부", async () => {
  const kv = createMemoryKV();
  const r = await requestCode("outsider@gmail.com", { kv, now: 0 });
  assert.equal(r.ok, false);
  assert.equal(r.reason, "email_not_allowed");
});

test("만료된 코드 거부", async () => {
  const kv = createMemoryKV();
  await requestCode("u@poscofuturem.com", { kv, now: 0, code: "222222", nonce: "N" });
  const v = await verifyCode("u@poscofuturem.com", "222222", "N", { kv, now: 11 * 60 * 1000 });
  assert.equal(v.ok, false);
  assert.equal(v.reason, "expired");
});

test("일회성: 한 번 성공하면 재사용 불가", async () => {
  const kv = createMemoryKV();
  await requestCode("u@poscofuturem.com", { kv, now: 0, code: "333333", nonce: "N" });
  assert.equal((await verifyCode("u@poscofuturem.com", "333333", "N", { kv, now: 1 })).ok, true);
  const again = await verifyCode("u@poscofuturem.com", "333333", "N", { kv, now: 2 });
  assert.equal(again.ok, false);
  assert.equal(again.reason, "no_code");
});

test("논스 불일치 거부 (세션 고정 방지)", async () => {
  const kv = createMemoryKV();
  await requestCode("u@poscofuturem.com", { kv, now: 0, code: "444444", nonce: "GOOD" });
  const v = await verifyCode("u@poscofuturem.com", "444444", "BAD", { kv, now: 1 });
  assert.equal(v.ok, false);
  assert.equal(v.reason, "nonce_mismatch");
});

test("5회 실패 시 코드 폐기", async () => {
  const kv = createMemoryKV();
  await requestCode("u@poscofuturem.com", { kv, now: 0, code: "555555", nonce: "N" });
  for (let i = 0; i < MAX_ATTEMPTS - 1; i++) {
    assert.equal((await verifyCode("u@poscofuturem.com", "000000", "N", { kv, now: 1 })).reason, "wrong_code");
  }
  const last = await verifyCode("u@poscofuturem.com", "000000", "N", { kv, now: 1 });
  assert.equal(last.reason, "too_many_attempts");
  assert.equal((await verifyCode("u@poscofuturem.com", "555555", "N", { kv, now: 1 })).reason, "no_code");
});

test("발급 제한: 5분 내 3회 초과 거부", async () => {
  const kv = createMemoryKV();
  for (let i = 0; i < 3; i++) {
    assert.equal((await requestCode("u@poscofuturem.com", { kv, now: i })).ok, true);
  }
  const r = await requestCode("u@poscofuturem.com", { kv, now: 4 });
  assert.equal(r.ok, false);
  assert.equal(r.reason, "rate_limited");
});

test("서로 다른 KV 인스턴스는 상태를 공유하지 않는다(서버리스 문제 재현)", async () => {
  const issuer = createMemoryKV();
  const verifier = createMemoryKV(); // 다른 인스턴스
  await requestCode("u@poscofuturem.com", { kv: issuer, now: 0, code: "999999", nonce: "N" });
  const v = await verifyCode("u@poscofuturem.com", "999999", "N", { kv: verifier, now: 1 });
  assert.equal(v.reason, "no_code"); // ← 공유 KV(운영)라면 성공했을 흐름
});
