// /api/articles — L1 이상. L1 응답에는 L2 필드가 없다 (INV-8).
import { NextResponse } from "next/server";
import { levelFromCookieHeader } from "../../../lib/request.ts";
import { articlesResponse } from "../../../lib/api.ts";

export const runtime = "nodejs"; // node:crypto 서명 검증 필요

export async function GET(req: Request) {
  const level = levelFromCookieHeader(req.headers.get("cookie"));
  const { status, body } = articlesResponse(level);
  return NextResponse.json(body, { status });
}
