// 서명 세션 쿠키 (HMAC-SHA256). 프레임워크 비의존.
//   - 완전 검증(verifySession)은 /api/* (Node 런타임)에서 수행 → 진짜 보안 경계.
//   - middleware(Edge)는 서명 검증 없이 만료만 보는 readClaims 로 리다이렉트 판단만 한다.
//     (INV-8: 실제 필드 필터링·레벨 게이트는 서버 API 가 담당)
import crypto from "node:crypto";
import type { Level } from "./levels.ts";

export const COOKIE = "pnb_session";
export const SESSION_TTL_MS = 30 * 24 * 60 * 60 * 1000; // 30일 (docs §4.12.2)

export interface SessionPayload {
  email: string;
  level: Level;
  iat: number;
  exp: number;
}

// 세션은 서버 상태가 없는(stateless) 서명 쿠키다 → 서버리스 인스턴스 불일치 문제 없음.
// 단, 모든 인스턴스가 같은 SESSION_SECRET(env)을 공유해야 서명이 호환된다.
// 운영에서 미설정이면 인스턴스마다 기본값이 같아 동작은 하나 보안상 반드시 설정할 것.
function secret(): string {
  return process.env.SESSION_SECRET || "dev-insecure-secret-change-me";
}

function hmac(body: string, key: string): string {
  return crypto.createHmac("sha256", key).update(body).digest("base64url");
}

function safeEqual(a: string, b: string): boolean {
  const ab = Buffer.from(a);
  const bb = Buffer.from(b);
  if (ab.length !== bb.length) return false;
  return crypto.timingSafeEqual(ab, bb);
}

export function signSession(
  payload: Omit<SessionPayload, "iat" | "exp">,
  opts?: { now?: number; ttlMs?: number; key?: string }
): string {
  const now = opts?.now ?? Date.now();
  const full: SessionPayload = {
    ...payload,
    iat: now,
    exp: now + (opts?.ttlMs ?? SESSION_TTL_MS),
  };
  const body = Buffer.from(JSON.stringify(full)).toString("base64url");
  return `${body}.${hmac(body, opts?.key ?? secret())}`;
}

// 완전 검증 — 서명 대조 + 만료. 실패 시 null (fail-closed).
export function verifySession(
  token: string | null | undefined,
  opts?: { now?: number; key?: string }
): SessionPayload | null {
  if (!token) return null;
  const dot = token.lastIndexOf(".");
  if (dot <= 0) return null;
  const body = token.slice(0, dot);
  const sig = token.slice(dot + 1);
  if (!safeEqual(sig, hmac(body, opts?.key ?? secret()))) return null;
  try {
    const payload = JSON.parse(Buffer.from(body, "base64url").toString("utf8")) as SessionPayload;
    if (typeof payload.exp !== "number" || (opts?.now ?? Date.now()) > payload.exp) return null;
    return payload;
  } catch {
    return null;
  }
}

// 서명 검증 없이 클레임만 디코드 (Edge middleware 리다이렉트 판단 전용).
// ⚠️ 신뢰 경계 아님 — 진짜 검증은 verifySession(서버 API).
export function readClaims(
  token: string | null | undefined,
  now: number = Date.now()
): SessionPayload | null {
  if (!token) return null;
  const dot = token.lastIndexOf(".");
  if (dot <= 0) return null;
  try {
    const payload = JSON.parse(Buffer.from(token.slice(0, dot), "base64url").toString("utf8")) as SessionPayload;
    if (typeof payload.exp !== "number" || now > payload.exp) return null;
    return payload;
  } catch {
    return null;
  }
}
