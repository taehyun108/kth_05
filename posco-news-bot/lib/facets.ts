// 통합 필터 (facets) + 모바일 pill 렌더 규칙 (docs/04-frontend.md §4.6.3)
//   필터 = 그룹 간 AND, 그룹 내 OR. 그룹 = facet prefix(track:/cat:/country:/topic:/company:)
import type { TrackId } from "./taxonomy.ts";
import { categoriesForTrack } from "./taxonomy.ts";

function groupOf(facet: string): string {
  const i = facet.indexOf(":");
  return i >= 0 ? facet.slice(0, i) : facet;
}

// 선택된 facet 들을 그룹별로 묶는다.
export function groupFacets(active: string[]): Record<string, Set<string>> {
  const groups: Record<string, Set<string>> = {};
  for (const f of active) {
    const g = groupOf(f);
    (groups[g] ??= new Set()).add(f);
  }
  return groups;
}

// 기사(facets 배열)가 선택 조건에 맞는가. 그룹 간 AND, 그룹 내 OR.
export function articleMatches(articleFacets: string[], active: string[]): boolean {
  if (!active || active.length === 0) return true;
  const artSet = new Set(articleFacets || []);
  const groups = groupFacets(active);
  for (const g of Object.keys(groups)) {
    let hit = false;
    for (const f of groups[g]) {
      if (artSet.has(f)) { hit = true; break; }
    }
    if (!hit) return false; // 이 그룹에서 하나도 안 맞으면 탈락 (AND)
  }
  return true;
}

export function filterArticles<T extends { facets?: string[] }>(articles: T[], active: string[]): T[] {
  return (articles || []).filter((a) => articleMatches(a.facets || [], active));
}

// 모바일 pill 폭발 방지 (§4.6.3):
//   트랙 미선택 → 트랙 3개(4개)만. 트랙 선택 → 그 트랙 카테고리만 렌더.
export function visiblePills(activeTrack: TrackId | null): { kind: "tracks" | "categories"; items: string[] } {
  if (!activeTrack) {
    return { kind: "tracks", items: ["posco", "battery", "policy", "trade"] };
  }
  return { kind: "categories", items: categoriesForTrack(activeTrack) };
}
