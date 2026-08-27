// 세션 검증 → 미인증 시 /login 리다이렉트 (docs/05-auth.md §3.2, §4.12.3)
// ⚠️ Edge 런타임: 서명 검증(node:crypto)은 불가하므로 여기서는 클레임(만료)만 본다.
//    진짜 보안 경계는 /api/* (Node 런타임 verifySession + 레벨 게이트, INV-8).
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { COOKIE, readClaims } from "./lib/session.ts";
import { safeNext } from "./lib/guard.ts";

// 인증 없이 접근 가능한 경로
const PUBLIC_PATHS = ["/login", "/api/auth"];

function isPublic(pathname: string): boolean {
  if (PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(p + "/"))) return true;
  // 정적 자산·파비콘 등
  if (pathname.startsWith("/_next") || pathname === "/favicon.ico" || pathname === "/") return true;
  return false;
}

export function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  if (isPublic(pathname)) return NextResponse.next();

  const token = req.cookies.get(COOKIE)?.value;
  const claims = readClaims(token);
  if (claims) return NextResponse.next();

  // API 는 리다이렉트 대신 401 (클라이언트 fetch 가 처리)
  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = "";
  url.searchParams.set("next", safeNext(pathname + (search || "")));
  return NextResponse.redirect(url);
}

export const config = {
  // 정적 자산 제외 전 경로
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
