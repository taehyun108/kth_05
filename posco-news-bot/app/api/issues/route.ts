// /api/issues — L2 전용 (SWOT). L1 세션은 403 (docs/05-auth.md §4.12.5).
import { NextResponse } from "next/server";
import { levelFromCookieHeader } from "../../../lib/request.ts";
import { issuesResponse } from "../../../lib/api.ts";

export const runtime = "nodejs";

export async function GET(req: Request) {
  const level = levelFromCookieHeader(req.headers.get("cookie"));
  const { status, body } = issuesResponse(level);
  // TODO(P6): SWOT 접근 감사 로그 (이메일·시각·이슈 id)
  return NextResponse.json(body, { status });
}
