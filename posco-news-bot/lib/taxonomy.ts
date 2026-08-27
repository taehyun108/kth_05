// 트랙·카테고리·배지 상수 (docs/04-frontend.md §4.6.2)
export type TrackId = "posco" | "battery" | "policy" | "trade";

export interface TrackDef { label: string; emoji: string; home: string; }
export interface CategoryDef { track: TrackId; label: string; short: string; emoji: string; }

export const TRACKS: Record<TrackId, TrackDef> = {
  posco: { label: "포스코 그룹", emoji: "🏢", home: "/posco/" },
  battery: { label: "이차전지 산업", emoji: "🔋", home: "/posco/" },
  policy: { label: "정책·산업동향", emoji: "📜", home: "/policy/" },
  trade: { label: "통상·규제", emoji: "⚔️", home: "/trade/" },
};

export const CATEGORIES: Record<string, CategoryDef> = {
  holdings: { track: "posco", label: "포스코홀딩스", short: "홀딩스", emoji: "🏢" },
  "posco-steel": { track: "posco", label: "포스코(철강)", short: "철강", emoji: "🏭" },
  futurem: { track: "posco", label: "포스코퓨처엠", short: "퓨처엠", emoji: "🔋" },
  international: { track: "posco", label: "포스코인터내셔널", short: "인터", emoji: "🌐" },
  enc: { track: "posco", label: "포스코이앤씨", short: "이앤씨", emoji: "🏗️" },
  dx: { track: "posco", label: "포스코DX", short: "DX", emoji: "💻" },
  group: { track: "posco", label: "그룹 전반", short: "그룹", emoji: "🧩" },
  "cell-kr": { track: "battery", label: "국내 셀", short: "국내셀", emoji: "🇰🇷" },
  "cell-global": { track: "battery", label: "해외 셀", short: "해외셀", emoji: "🌏" },
  "mat-kr": { track: "battery", label: "국내 소재", short: "국내소재", emoji: "⚗️" },
  "mat-global": { track: "battery", label: "해외 소재", short: "해외소재", emoji: "🧪" },
  raw: { track: "battery", label: "원료·광물", short: "원료", emoji: "⛏️" },
  demand: { track: "battery", label: "전방·응용", short: "전방", emoji: "🚗" },
  tech: { track: "battery", label: "기술·연구", short: "기술", emoji: "🔬" },
  equip: { track: "battery", label: "장비·공정", short: "장비", emoji: "🛠️" },
  "pol-kr": { track: "policy", label: "국내 정책", short: "국내", emoji: "🇰🇷" },
  "pol-us": { track: "policy", label: "미국", short: "미국", emoji: "🇺🇸" },
  "pol-eu": { track: "policy", label: "EU", short: "EU", emoji: "🇪🇺" },
  "pol-cn": { track: "policy", label: "중국", short: "중국", emoji: "🇨🇳" },
  "pol-global": { track: "policy", label: "기타 국가", short: "기타국", emoji: "🌍" },
  "pol-law": { track: "policy", label: "법령·행정예고", short: "법령", emoji: "⚖️" },
  "pol-trend": { track: "policy", label: "산업 현황·트렌드", short: "트렌드", emoji: "📊" },
  "trade-tariff": { track: "trade", label: "관세·무역분쟁", short: "관세", emoji: "⚔️" },
  "trade-remedy": { track: "trade", label: "무역구제", short: "구제", emoji: "⚖️" },
  "trade-export": { track: "trade", label: "수출통제·제재", short: "수출통제", emoji: "🚫" },
  "trade-origin": { track: "trade", label: "원산지·FTA", short: "원산지", emoji: "📑" },
  "trade-supply": { track: "trade", label: "공급망 규제", short: "공급망", emoji: "🔗" },
  "trade-country": { track: "trade", label: "국가별 현황", short: "국가별", emoji: "🗺️" },
};

export interface BadgeDef { label: string; cls: string; }

export const TONE: Record<string, BadgeDef> = {
  positive: { label: "🟢 긍정", cls: "badge-tone-positive" },
  neutral: { label: "⚪ 중립", cls: "badge-tone-neutral" },
  negative: { label: "🔴 부정", cls: "badge-tone-negative" },
  crisis: { label: "🚨 위기", cls: "badge-tone-crisis" },
};

export const IMPACT: Record<string, BadgeDef> = {
  high: { label: "중요도 상", cls: "badge-impact-high" },
  mid: { label: "중", cls: "badge-impact-mid" },
  low: { label: "하", cls: "badge-impact-low" },
};

export const POLICY_STAGE: Record<string, BadgeDef> = {
  discussion: { label: "논의", cls: "badge-stage-discussion" },
  proposed: { label: "예고", cls: "badge-stage-proposed" },
  enacted: { label: "확정", cls: "badge-stage-enacted" },
  effective: { label: "시행", cls: "badge-stage-effective" },
  amended: { label: "개정", cls: "badge-stage-amended" },
};

export const DISPUTE_STAGE: Record<string, BadgeDef> = {
  initiated: { label: "조사개시", cls: "badge-dispute-initiated" },
  preliminary: { label: "예비판정", cls: "badge-dispute-preliminary" },
  final: { label: "최종판정", cls: "badge-dispute-final" },
  in_force: { label: "발효", cls: "badge-dispute-inforce" },
  negotiating: { label: "협상중", cls: "badge-dispute-negotiating" },
  terminated: { label: "종료", cls: "badge-dispute-terminated" },
};

export function categoriesForTrack(track: TrackId): string[] {
  return Object.keys(CATEGORIES).filter((c) => CATEGORIES[c].track === track);
}
