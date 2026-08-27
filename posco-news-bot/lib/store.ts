// 로그인 코드 저장소 — KV 로 해결(서버리스 인스턴스 간 공유).
//   env(KV_REST_API_URL/TOKEN) 있으면 Vercel KV, 없으면 로컬 인메모리(resolveKV).
//
// 세션은 별개다: 서명(HMAC) 쿠키라 서버 상태가 없어 인스턴스 불일치 문제가 없다.
//   단, 모든 인스턴스가 같은 SESSION_SECRET(env)을 공유해야 서명이 호환된다.
import { resolveKV } from "./kvstore.ts";
import type { KVStore } from "./kvstore.ts";

export function loginKV(): KVStore {
  return resolveKV();
}

export const NONCE_COOKIE = "pnb_nonce";
