// 요청에서 세션 추출 (Node 런타임, 완전 서명 검증). route.ts 가 사용.
import { COOKIE, verifySession } from "./session.ts";
import type { SessionPayload } from "./session.ts";
import type { Level } from "./levels.ts";

export function parseCookies(header: string | null | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  if (!header) return out;
  for (const part of header.split(";")) {
    const i = part.indexOf("=");
    if (i < 0) continue;
    const k = part.slice(0, i).trim();
    const v = part.slice(i + 1).trim();
    if (k) out[k] = decodeURIComponent(v);
  }
  return out;
}

export function sessionFromCookieHeader(header: string | null | undefined): SessionPayload | null {
  const token = parseCookies(header)[COOKIE];
  return verifySession(token);
}

export function levelFromCookieHeader(header: string | null | undefined): Level | null {
  return sessionFromCookieHeader(header)?.level ?? null;
}
