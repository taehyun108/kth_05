// /api/policies — L1은 board 축약본, L2는 full(our_position·policy_ask 포함).
import { NextResponse } from "next/server";
import { levelFromCookieHeader } from "../../../lib/request.ts";
import { policiesResponse } from "../../../lib/api.ts";

export const runtime = "nodejs";

export async function GET(req: Request) {
  const level = levelFromCookieHeader(req.headers.get("cookie"));
  const { status, body } = policiesResponse(level);
  return NextResponse.json(body, { status });
}
