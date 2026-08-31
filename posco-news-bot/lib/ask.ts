// Q&A 챗봇 RAG 코어 (docs/08-chatbot.md).
//   질문 → 슬롯 추출 → facets 필터 + 스코어링 → 상위 8건 → 근거 각주 답변
//
// ★보안 경계(INV-3)★: 메신저·미인증·L1 세션에는 issues(SWOT)를 ★컨텍스트에 로드조차 안 한다★.
//   프롬프트로 "말하지 마라"는 방어선이 아니다 — 소스를 아예 주입하지 않는다.
import type { Level } from "./levels.ts";

export type Channel = "web" | "telegram" | "kakao";

export interface Article {
  id: string; title?: string; summary?: string; url?: string; date?: string;
  track?: string; tone?: string; facets?: string[];
  posco_relevance?: string;
}

// ── 슬롯 추출 (결정론 — LLM은 최종 문장만, 검색 슬롯은 규칙) ─────────────────

const COMPANY_ALIASES: Record<string, string[]> = {
  futurem: ["포스코퓨처엠", "퓨처엠"], posco: ["포스코"], CATL: ["catl", "닝더스다이"],
  "에코프로비엠": ["에코프로"], "LG에너지솔루션": ["lg에너지솔루션", "lg엔솔"],
  "삼성SDI": ["삼성sdi"], "SK온": ["sk온"],
};
const COUNTRY_ALIASES: Record<string, string[]> = {
  KR: ["한국", "국내"], US: ["미국"], EU: ["eu", "유럽"], CN: ["중국"], JP: ["일본"],
};
const TRACK_HINTS: Record<string, string[]> = {
  posco: ["포스코", "퓨처엠", "계열사"], battery: ["배터리", "이차전지", "셀", "소재"],
  policy: ["정책", "지원", "세액공제", "규정", "법"], trade: ["관세", "통상", "수출통제", "무역"],
};
const TONE_HINTS: Record<string, string[]> = {
  positive: ["긍정", "호재"], negative: ["부정", "악재"], crisis: ["위기", "사고"], neutral: ["중립"],
};
const STOP = new Set(["기사", "정리", "해줘", "관련", "최근", "이번", "우리", "어떤", "찾아줘", "비교",
  "만들어줘", "동향", "무엇", "뭐야", "알려줘", "그리고", "대한", "대해"]);

export interface Slots {
  companies: string[]; countries: string[]; tracks: string[]; tones: string[];
  topics: string[]; days: number | null;
}

function matchAliases(low: string, table: Record<string, string[]>): string[] {
  const out: string[] = [];
  for (const [label, aliases] of Object.entries(table)) {
    if ([label.toLowerCase(), ...aliases].some((a) => low.includes(a.toLowerCase()))) out.push(label);
  }
  return out;
}

export function extractSlots(question: string): Slots {
  const low = (question || "").toLowerCase();
  let days: number | null = null;
  if (low.includes("이번 주") || low.includes("이번주") || low.includes("주간")) days = 7;
  else if (low.includes("한 달") || low.includes("한달") || low.includes("월간")) days = 30;
  else if (low.includes("오늘") || low.includes("어제")) days = 2;
  const topics = (question.match(/[0-9A-Za-z가-힣]{2,}/g) || [])
    .filter((t) => !STOP.has(t) && !/^\d+$/.test(t));
  return {
    companies: matchAliases(low, COMPANY_ALIASES),
    countries: matchAliases(low, COUNTRY_ALIASES),
    tracks: matchAliases(low, TRACK_HINTS),
    tones: matchAliases(low, TONE_HINTS),
    topics,
    days,
  };
}

// ── 스코어링 (facet 매칭 + 용어 겹침, BM25-lite) ────────────────────────────

export function scoreArticle(a: Article, slots: Slots): number {
  const facets = new Set(a.facets || []);
  const hay = `${a.title || ""} ${a.summary || ""}`.toLowerCase();
  let s = 0;
  for (const c of slots.companies) if (facets.has(`company:${c}`) || hay.includes(c.toLowerCase())) s += 3;
  for (const c of slots.countries) if (facets.has(`country:${c}`)) s += 2;
  for (const t of slots.tracks) if (facets.has(`track:${t}`)) s += 2;
  if (slots.tones.length && a.tone && slots.tones.includes(a.tone)) s += 2;
  for (const t of slots.topics) if (facets.has(`topic:${t}`) || hay.includes(t.toLowerCase())) s += 1;
  return s;
}

function withinDays(a: Article, days: number | null): boolean {
  if (!days || !a.date) return true;
  const d = Date.parse(a.date);
  if (Number.isNaN(d)) return true;
  return (Date.now() - d) <= days * 864e5 + 864e5; // 여유 1일
}

// 근거 판정: 회사/국가/토픽 등 ★구체 매칭★이 하나라도 있어야 한다.
// 트랙·논조 힌트(예: "배터리")만으로는 grounded 로 보지 않는다 → 추측 방지.
export function hasSpecificMatch(a: Article, slots: Slots): boolean {
  const facets = new Set(a.facets || []);
  const hay = `${a.title || ""} ${a.summary || ""}`.toLowerCase();
  for (const c of slots.companies) if (facets.has(`company:${c}`) || hay.includes(c.toLowerCase())) return true;
  for (const c of slots.countries) if (facets.has(`country:${c}`)) return true;
  for (const t of slots.topics) if (facets.has(`topic:${t}`) || hay.includes(t.toLowerCase())) return true;
  return false;
}

export function retrieve(question: string, corpus: Article[], topK = 8): { slots: Slots; hits: Article[] } {
  const slots = extractSlots(question);
  const scored = (corpus || [])
    .filter((a) => withinDays(a, slots.days))
    .map((a) => ({ a, s: scoreArticle(a, slots) }))
    .filter((x) => x.s > 0 && hasSpecificMatch(x.a, slots))
    .sort((x, y) => y.s - x.s || (y.a.date || "").localeCompare(x.a.date || ""));
  return { slots, hits: scored.slice(0, topK).map((x) => x.a) };
}

// ── 채널×레벨 접근 스코프 (핵심 보안 게이트) ────────────────────────────────

export interface Scope { includeIssues: boolean; poscoOnly: boolean; }

export function resolveScope(channel: Channel, level: Level | null | undefined): Scope {
  // issues(SWOT)는 오직 웹 + L2 에서만. 메신저는 절대 불가.
  const includeIssues = channel === "web" && level === "L2";
  const poscoOnly = channel === "kakao"; // 카톡은 포스코 관련만
  return { includeIssues, poscoOnly };
}

// ── 답변 조립 (근거 없으면 '수집된 기사에 없습니다', 각주 필수) ─────────────

const L2_STRIP = ["swot", "시사점", "policy_ask", "정책건의", "futurem_implication", "our_position", "대응논리"];

// 메신저 이중 차단: 혹시라도 L2 문구가 섞이면 후처리로 제거(1차 방어는 미로드).
export function stripL2(text: string): string {
  const low = text.toLowerCase();
  if (L2_STRIP.some((t) => low.includes(t))) {
    return text.split("\n").filter((line) => !L2_STRIP.some((t) => line.toLowerCase().includes(t))).join("\n");
  }
  return text;
}

export interface Answer { grounded: boolean; answer: string; citations: string[]; scope: Scope; }

export function assembleAnswer(hits: Article[], scope: Scope, opts?: { law?: boolean; hasLawKey?: boolean }): Answer {
  if (opts?.law && !opts.hasLawKey) {
    return { grounded: false, scope, citations: [],
      answer: "법령 실시간 조회는 현재 미지원입니다(국가법령정보센터 인증키 필요). "
            + "※ 법률 자문이 아니며 정확한 해석은 법무 부서·법률전문가 확인이 필요합니다." };
  }
  if (!hits.length) {
    return { grounded: false, answer: "수집된 기사에 없습니다.", citations: [], scope };
  }
  const lines = hits.map((a) => `- ${a.summary || a.title || ""} [${a.id}]`);
  const citations = hits.map((a) => a.id);
  let answer = lines.join("\n");
  if (!scope.includeIssues) answer = stripL2(answer); // 메신저·L1 이중 차단
  return { grounded: true, answer, citations, scope };
}

// ── 진입점 ───────────────────────────────────────────────────────────────────

export interface AskInput {
  question: string; channel: Channel; level: Level | null | undefined;
  articles: Article[]; issues?: unknown[]; hasLawKey?: boolean;
}

// issues(SWOT)를 검색 대상 문서로 변환 — ★scope.includeIssues 일 때만 호출★.
function issueToArticle(iss: Record<string, unknown>): Article {
  const swot = (iss.swot || {}) as Record<string, { text?: string }[]>;
  const texts = ["S", "W", "O", "T"].flatMap((ax) => (swot[ax] || []).map((i) => i.text || ""));
  return {
    id: String(iss.issue_id || "issue"),
    title: String(iss.title || iss.issue_id || ""),
    summary: [String(iss.title || ""), ...texts].join(" ").trim(),
    facets: [],
  };
}

export function ask(input: AskInput): Answer {
  const scope = resolveScope(input.channel, input.level);
  const isLaw = /법령|조문|법에서|특별법|관리법|조항/.test(input.question);
  let corpus = [...(input.articles || [])];
  if (scope.poscoOnly) corpus = corpus.filter((a) => a.posco_relevance && a.posco_relevance !== "none");
  // ★L2 웹 세션만 issues 를 검색 대상에 포함★. 그 외엔 애초에 input.issues 가 없다.
  if (scope.includeIssues && input.issues) {
    corpus = corpus.concat((input.issues as Record<string, unknown>[]).map(issueToArticle));
  }
  const { hits } = retrieve(input.question, corpus);
  return assembleAnswer(hits, scope, { law: isLaw, hasLawKey: input.hasLawKey });
}
