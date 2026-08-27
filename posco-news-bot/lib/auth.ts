// 로그인 코드(6자리) 수명주기 (docs/05-auth.md §4.12.2).
//   만료 10분 · 5회 실패 시 폐기 · 이메일당 5분 내 3회 발급 · 일회성 · 논스(세션 고정 방지)
// 순수 로직 — store/clock/rng 를 주입해 결정론적으로 검증한다.
import crypto from "node:crypto";
import type { Level } from "./levels.ts";
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
  used: boolean;
}

export interface CodeStore {
  get(email: string): CodeRecord | null;
  set(email: string, rec: CodeRecord): void;
  del(email: string): void;
  recordIssue(email: string, at: number): void;
  issuesSince(email: string, since: number): number;
}

export function createMemoryStore(): CodeStore {
  const codes = new Map<string, CodeRecord>();
  const issues = new Map<string, number[]>();
  return {
    get: (email) => codes.get(email) ?? null,
    set: (email, rec) => void codes.set(email, rec),
    del: (email) => void codes.delete(email),
    recordIssue: (email, at) => {
      const arr = issues.get(email) ?? [];
      arr.push(at);
      issues.set(email, arr);
    },
    issuesSince: (email, since) => (issues.get(email) ?? []).filter((t) => t >= since).length,
  };
}

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

export function requestCode(
  emailRaw: string,
  opts: { store: CodeStore; now?: number; rng?: () => number; code?: string; nonce?: string }
): RequestResult {
  const email = normalizeEmail(emailRaw);
  const now = opts.now ?? Date.now();
  const level = levelForEmail(email);
  if (!level) return { ok: false, reason: "email_not_allowed" }; // 도메인/허용목록 밖 → 거부

  // 발급 제한: 5분 내 3회
  if (opts.store.issuesSince(email, now - ISSUE_WINDOW_MS) >= ISSUE_MAX) {
    return { ok: false, reason: "rate_limited" };
  }

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
    used: false,
  };
  opts.store.set(email, rec);
  opts.store.recordIssue(email, now);
  return { ok: true, code, nonce, level, expiresAt: rec.expiresAt };
}

export interface VerifyResult {
  ok: boolean;
  reason?: string;
  level?: Level;
  email?: string;
}

export function verifyCode(
  emailRaw: string,
  code: string,
  nonce: string,
  opts: { store: CodeStore; now?: number }
): VerifyResult {
  const email = normalizeEmail(emailRaw);
  const now = opts.now ?? Date.now();
  const rec = opts.store.get(email);
  if (!rec) return { ok: false, reason: "no_code" };
  if (rec.used) return { ok: false, reason: "already_used" };
  if (now > rec.expiresAt) {
    opts.store.del(email);
    return { ok: false, reason: "expired" };
  }
  if (rec.nonce !== nonce) {
    // 다른 기기에서 가로챈 코드 — 세션 고정 방지 (시도로 카운트)
    return bumpAttempt(email, rec, opts.store, "nonce_mismatch");
  }
  if (rec.codeHash !== hashCode(code, email)) {
    return bumpAttempt(email, rec, opts.store, "wrong_code");
  }
  // 성공 → 즉시 폐기 (일회성)
  rec.used = true;
  opts.store.set(email, rec);
  opts.store.del(email);
  return { ok: true, level: rec.level, email };
}

function bumpAttempt(email: string, rec: CodeRecord, store: CodeStore, reason: string): VerifyResult {
  rec.attempts += 1;
  if (rec.attempts >= MAX_ATTEMPTS) {
    store.del(email); // 5회 실패 → 코드 폐기, 재발급 필요
    return { ok: false, reason: "too_many_attempts" };
  }
  store.set(email, rec);
  return { ok: false, reason };
}
