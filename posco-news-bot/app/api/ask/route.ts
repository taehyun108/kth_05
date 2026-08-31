// POST /api/ask — 웹 Q&A. 세션 레벨로 검색 범위가 결정된다(L2만 SWOT 포함).
// 메신저(텔레그램·카톡)는 이 라우트가 아니라 봇이 ask() 코어를 channel 로 호출한다.
import { NextResponse } from "next/server";
import { levelFromCookieHeader } from "../../../lib/request.ts";
import { askResponse } from "../../../lib/api.ts";

export const runtime = "nodejs";

export async function POST(req: Request) {
  let question = "";
  try {
    ({ question } = await req.json());
  } catch {
    return NextResponse.json({ error: "bad_request" }, { status: 400 });
  }
  const level = levelFromCookieHeader(req.headers.get("cookie"));
  const { status, body } = askResponse(question || "", level);
  return NextResponse.json(body, { status });
}
