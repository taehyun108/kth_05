// POST /api/auth/request — 이메일 검증 → 6자리 코드 발급 → 사내 메일로 발송.
//   응답 본문에 코드를 담지 않는다. 논스는 httpOnly 쿠키로 브라우저에 바인딩(세션 고정 방지).
import { NextResponse } from "next/server";
import { requestCode } from "../../../../lib/auth.ts";
import { codeStore, NONCE_COOKIE } from "../../../../lib/store.ts";
import { sendLoginCode } from "../../../../lib/mailer.ts";

export const runtime = "nodejs";

export async function POST(req: Request) {
  let email = "";
  try {
    ({ email } = await req.json());
  } catch {
    return NextResponse.json({ error: "bad_request" }, { status: 400 });
  }

  const result = requestCode(email, { store: codeStore() });
  // 자격 미달·레이트리밋이어도 존재 여부를 노출하지 않도록 동일 응답(ok)로 통일.
  if (result.ok && result.code && result.nonce) {
    await sendLoginCode(email, result.code); // 메일 발송(개발 환경에선 로그)
  }

  const res = NextResponse.json({ ok: true });
  if (result.ok && result.nonce) {
    res.cookies.set(NONCE_COOKIE, result.nonce, {
      httpOnly: true,
      secure: true,
      sameSite: "lax",
      maxAge: 15 * 60, // 코드 만료(10분)보다 약간 길게
      path: "/",
    });
  }
  return res;
}
