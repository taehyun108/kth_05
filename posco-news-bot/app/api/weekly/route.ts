// /api/weekly — L2 전용 (주간 브리프·outlook). L1 세션은 403.
import { NextResponse } from "next/server";
import { levelFromCookieHeader } from "../../../lib/request.ts";
import { weeklyResponse } from "../../../lib/api.ts";

export const runtime = "nodejs";

export async function GET(req: Request) {
  const level = levelFromCookieHeader(req.headers.get("cookie"));
  const { status, body } = weeklyResponse(level);
  return NextResponse.json(body, { status });
}
