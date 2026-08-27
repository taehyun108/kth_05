// POST /api/auth/logout — 세션 쿠키 폐기.
import { NextResponse } from "next/server";
import { COOKIE } from "../../../../lib/session.ts";

export const runtime = "nodejs";

export async function POST() {
  const res = NextResponse.json({ ok: true });
  res.cookies.set(COOKIE, "", { path: "/", maxAge: 0 });
  return res;
}
