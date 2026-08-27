// 레벨 게이트 + 안전 리다이렉트 (docs/05-auth.md §4.12.3, §4.12.4)
import type { Level } from "./levels.ts";
import { atLeast } from "./levels.ts";

export interface GuardResult {
  ok: boolean;
  status: number; // 200 통과 · 401 미인증 · 403 권한부족
}

// 세션 레벨이 required 미만이면 차단. 미인증(null)=401, 인증했으나 부족=403.
export function requireLevel(sessionLevel: Level | null | undefined, required: Level): GuardResult {
  if (atLeast(sessionLevel, required)) return { ok: true, status: 200 };
  return { ok: false, status: sessionLevel ? 403 : 401 };
}

// next 파라미터는 자체 경로만 허용 (오픈 리다이렉트 방지, docs §4.12.3)
export function safeNext(next: string | null | undefined, fallback = "/posco/"): string {
  if (typeof next !== "string" || !next) return fallback;
  if (!next.startsWith("/")) return fallback; // 절대 URL 거부
  if (next.startsWith("//")) return fallback; // 프로토콜 상대 URL 거부
  if (next.includes("://") || next.includes("\\")) return fallback;
  if (next.includes("\n") || next.includes("\r")) return fallback;
  return next;
}

export function loginRedirect(pathname: string | null | undefined): string {
  return `/login?next=${encodeURIComponent(safeNext(pathname))}`;
}
