// 접근 레벨 모델 (docs/05-auth.md §3.2.1)
//   L0 미인증 · L1 사내 구성원 · L2 대외협력(SWOT/시사점)
// 프레임워크 비의존 — Next 없이 node --test 로 검증한다.

export type Level = "L0" | "L1" | "L2";

export const LEVELS: Level[] = ["L0", "L1", "L2"];

export function rank(level: Level | null | undefined): number {
  if (level === "L2") return 2;
  if (level === "L1") return 1;
  return 0;
}

export function atLeast(level: Level | null | undefined, required: Level): boolean {
  return rank(level) >= rank(required);
}
