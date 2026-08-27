// 코드 저장소 싱글턴 (개발용 인메모리).
// ⚠️ 서버리스에서는 인스턴스 간 공유되지 않는다. 운영 전환 시 Vercel KV/Redis 로 교체.
import { createMemoryStore } from "./auth.ts";
import type { CodeStore } from "./auth.ts";

const g = globalThis as unknown as { __pnbCodeStore?: CodeStore };

export function codeStore(): CodeStore {
  if (!g.__pnbCodeStore) g.__pnbCodeStore = createMemoryStore();
  return g.__pnbCodeStore;
}

export const NONCE_COOKIE = "pnb_nonce";
