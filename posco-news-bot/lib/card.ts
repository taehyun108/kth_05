// 카드 렌더 결정 (순수) — docs/04-frontend.md §4.6.4
//   INV-6: L1/L2 산출 필드(tone·impact 등)는 optional. 없어도 카드가 정상 렌더된다.
//   요구사항: summary_method === 'extractive' 이면 "⚙️ 규칙요약" 배지 표시.
import { TRACKS, CATEGORIES, TONE, IMPACT, POLICY_STAGE, DISPUTE_STAGE } from "./taxonomy.ts";
import type { BadgeDef } from "./taxonomy.ts";

export interface Article {
  id: string;
  title: string;
  url?: string;
  outlet?: string;
  date?: string;
  track?: string;
  category?: string;
  summary?: string;
  bullets?: string[];
  topics?: string[];
  posco_relevance?: string;
  // L1/L2 산출 — 전부 optional (INV-6)
  tone?: string;
  impact?: string;
  policy_stage?: string;
  dispute_stage?: string;
  summary_method?: string;
}

export interface Badge extends BadgeDef { group: string; }

// 규칙요약(추출) 배지 — L0 산출임을 카드에 명시.
export const RULE_SUMMARY_BADGE: Badge = { group: "summary", label: "⚙️ 규칙요약", cls: "badge-rule-summary" };

// 카드에 표시할 배지들. 없는 필드는 건너뛴다(빈 배열이어도 카드는 렌더된다).
export function cardBadges(a: Article): Badge[] {
  const badges: Badge[] = [];
  const track = a.track && TRACKS[a.track as keyof typeof TRACKS];
  if (track) badges.push({ group: "track", label: `${track.emoji} ${track.label}`, cls: "badge-track" });
  const cat = a.category && CATEGORIES[a.category];
  if (cat) badges.push({ group: "category", label: `${cat.emoji} ${cat.label}`, cls: "badge-category" });

  if (a.tone && TONE[a.tone]) badges.push({ group: "tone", ...TONE[a.tone] });
  if (a.impact && IMPACT[a.impact]) badges.push({ group: "impact", ...IMPACT[a.impact] });
  if (a.policy_stage && POLICY_STAGE[a.policy_stage]) badges.push({ group: "policy_stage", ...POLICY_STAGE[a.policy_stage] });
  if (a.dispute_stage && DISPUTE_STAGE[a.dispute_stage]) badges.push({ group: "dispute_stage", ...DISPUTE_STAGE[a.dispute_stage] });

  // L0 추출 요약이면 규칙요약 배지 (L1 생성요약으로 승격되면 summary_method 가 바뀌어 사라진다)
  if (a.summary_method === "extractive") badges.push(RULE_SUMMARY_BADGE);
  return badges;
}

// 카드 본문에 쓸 안전한 뷰모델 — 누락 필드에 기본값을 채워 렌더가 깨지지 않게.
export interface CardView {
  id: string;
  title: string;
  href: string;
  summary: string;
  bullets: string[];
  topics: string[];
  outlet: string;
  date: string;
  badges: Badge[];
  isExtractive: boolean;
}

export function toCardView(a: Article): CardView {
  return {
    id: a.id,
    title: a.title || "(제목 없음)",
    href: a.url || `/posco/articles/${a.id}`,
    summary: a.summary || "",
    bullets: a.bullets || [],
    topics: a.topics || [],
    outlet: a.outlet || "",
    date: a.date || "",
    badges: cardBadges(a),
    isExtractive: a.summary_method === "extractive",
  };
}
