// 로그인 코드(6자리) 수명주기 (docs/05-auth.md §4.12.2).
//   만료 10분 · 5회 실패 시 폐기 · 이메일당 5분 내 3회 발급 · 일회성 · 논스(세션 고정 방지)
// KVStore 로 상태를 보관해 서버리스 인스턴스 간 공유한다(주입식 — 테스트는 MemoryKV).
import crypto from "node:crypto";
import type { Level } from "./levels.ts";
import type { KVStore } from "./kvstore.ts";
import { levelForEmail, normalizeEmail } from "./allowlist.ts";

export const CODE_TTL_MS = 10 * 60 * 1000; // 10분
export const MAX_ATTEMPTS = 5; // 5회 실패 시 코드 폐기
export const ISSUE_WINDOW_MS = 5 * 60 * 1000; // 발급 제한 창
export const ISSUE_MAX = 3; // 창 내 최대 발급

export interface CodeRecord {
  email: string;
  codeHash: string;
  nonce: string;
  level: Level;
  createdAt: number;
  expiresAt: number;
  attempts: number;
}

const codeKey = (email: string) => `login:code:${email}`;
const issueKey = (email: string) => `login:issue:${email}`;

function hashCode(code: string, email: string): string {
  const key = process.env.SESSION_SECRET || "dev-insecure-secret-change-me";
  return crypto.createHmac("sha256", key).update(`${email}:${code}`).digest("hex");
}

export function generateCode(rng: () => number = Math.random): string {
  return String(Math.floor(rng() * 1_000_000)).padStart(6, "0");
}

export function generateNonce(): string {
  return crypto.randomBytes(16).toString("hex");
}

export interface RequestResult {
  ok: boolean;
  reason?: string;
  code?: string; // 호출측이 메일로 발송 (응답 본문에 넣지 않는다)
  nonce?: string;
  level?: Level;
  expiresAt?: number;
}

export async function requestCode(
  emailRaw: string,
  opts: { kv: KVStore; now?: number; rng?: () => number; code?: string; nonce?: string }
): Promise<RequestResult> {
  const email = normalizeEmail(emailRaw);
  const now = opts.now ?? Date.now();
  const level = levelForEmail(email);
  if (!level) return { ok: false, reason: "email_not_allowed" }; // 도메인/허용목록 밖

  // 발급 제한: 5분 내 3회 (고정창 카운터)
  const count = await opts.kv.incrWindow(issueKey(email), ISSUE_WINDOW_MS, now);
  if (count > ISSUE_MAX) return { ok: false, reason: "rate_limited" };

  const code = opts.code ?? generateCode(opts.rng);
  const nonce = opts.nonce ?? generateNonce();
  const rec: CodeRecord = {
    email,
    codeHash: hashCode(code, email),
    nonce,
    level,
    createdAt: now,
    expiresAt: now + CODE_TTL_MS,
    attempts: 0,
  };
  await opts.kv.set(codeKey(email), JSON.stringify(rec), CODE_TTL_MS);
  return { ok: true, code, nonce, level, expiresAt: rec.expiresAt };
}

export interface VerifyResult {
  ok: boolean;
  reason?: string;
  level?: Level;
  email?: string;
}

export async function verifyCode(
  emailRaw: string,
  code: string,
  nonce: string,
  opts: { kv: KVStore; now?: number }
): Promise<VerifyResult> {
  const email = normalizeEmail(emailRaw);
  const now = opts.now ?? Date.now();
  const raw = await opts.kv.get(codeKey(email));
  if (!raw) return { ok: false, reason: "no_code" };
  let rec: CodeRecord;
  try {
    rec = JSON.parse(raw) as CodeRecord;
  } catch {
    await opts.kv.del(codeKey(email));
    return { ok: false, reason: "corrupt" };
  }
  if (now > rec.expiresAt) {
    await opts.kv.del(codeKey(email));
    return { ok: false, reason: "expired" };
  }
  if (rec.nonce !== nonce) {
    return bumpAttempt(email, rec, opts.kv, "nonce_mismatch", now); // 세션 고정 방지
  }
  if (rec.codeHash !== hashCode(code, email)) {
    return bumpAttempt(email, rec, opts.kv, "wrong_code", now);
  }
  await opts.kv.del(codeKey(email)); // 성공 → 즉시 폐기 (일회성)
  return { ok: true, level: rec.level, email };
}

async function bumpAttempt(
  email: string,
  rec: CodeRecord,
  kv: KVStore,
  reason: string,
  now: number
): Promise<VerifyResult> {
  rec.attempts += 1;
  if (rec.attempts >= MAX_ATTEMPTS) {
    await kv.del(codeKey(email)); // 5회 실패 → 코드 폐기, 재발급 필요
    return { ok: false, reason: "too_many_attempts" };
  }
  // ★TTL 은 검증과 같은 시계(now)로 계산한다★ — Date.now() 를 섞으면 주입 시계와
  // 어긋나 TTL 이 음수→1ms 로 찍혀 코드가 조기 소멸(간헐 실패의 원인이었다).
  const ttl = Math.max(1, rec.expiresAt - now);
  await kv.set(codeKey(email), JSON.stringify(rec), ttl);
  return { ok: false, reason };
}
