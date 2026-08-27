// POST /api/auth/verify — 코드+논스 검증 → 세션 쿠키 발급 → next 경로 반환.
import { NextResponse } from "next/server";
import { verifyCode } from "../../../../lib/auth.ts";
import { codeStore, NONCE_COOKIE } from "../../../../lib/store.ts";
import { signSession, COOKIE, SESSION_TTL_MS } from "../../../../lib/session.ts";
import { parseCookies } from "../../../../lib/request.ts";
import { safeNext } from "../../../../lib/guard.ts";

export const runtime = "nodejs";

export async function POST(req: Request) {
  let email = "";
  let code = "";
  let next = "/posco/";
  try {
    const b = await req.json();
    email = b.email;
    code = b.code;
    next = b.next ?? "/posco/";
  } catch {
    return NextResponse.json({ error: "bad_request" }, { status: 400 });
  }

  const nonce = parseCookies(req.headers.get("cookie"))[NONCE_COOKIE] || "";
  const result = verifyCode(email, code, nonce, { store: codeStore() });
  if (!result.ok || !result.level) {
    return NextResponse.json({ ok: false, reason: result.reason }, { status: 401 });
  }

  const token = signSession({ email: result.email!, level: result.level });
  const res = NextResponse.json({ ok: true, next: safeNext(next), level: result.level });
  res.cookies.set(COOKIE, token, {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    maxAge: Math.floor(SESSION_TTL_MS / 1000),
    path: "/",
  });
  res.cookies.set(NONCE_COOKIE, "", { path: "/", maxAge: 0 }); // 논스 폐기
  return res;
}
