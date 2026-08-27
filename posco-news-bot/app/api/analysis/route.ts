// /api/analysis — L2 전용 (시사점·swot_axis). L1 세션은 403.
import { NextResponse } from "next/server";
import { levelFromCookieHeader } from "../../../lib/request.ts";
import { analysisResponse } from "../../../lib/api.ts";

export const runtime = "nodejs";

export async function GET(req: Request) {
  const level = levelFromCookieHeader(req.headers.get("cookie"));
  const { status, body } = analysisResponse(level);
  return NextResponse.json(body, { status });
}
