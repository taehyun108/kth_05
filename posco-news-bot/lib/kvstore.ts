// KV 저장소 추상화 — 서버리스에서 인스턴스 간 상태 공유 (docs/05-auth.md §4.12.2).
//   로컬/테스트: MemoryKV · 운영: Vercel KV(Upstash) REST API (추가 패키지 불요, fetch)
// ⚠️ 인메모리는 서버리스에서 인스턴스마다 분리된다 → 코드 발급/검증 인스턴스 불일치로
//    간헐적 로그인 실패. 운영에서는 반드시 외부 KV 를 쓴다(resolveKV 가 env 로 자동 선택).

export interface KVStore {
  get(key: string): Promise<string | null>;
  set(key: string, value: string, ttlMs?: number): Promise<void>;
  del(key: string): Promise<void>;
  // 고정창 카운터 (레이트리밋) — 현재 창의 누적 카운트를 반환
  incrWindow(key: string, windowMs: number, now?: number): Promise<number>;
}

// ── 로컬/테스트용 인메모리 ────────────────────────────────────────────────
export function createMemoryKV(): KVStore {
  const store = new Map<string, { v: string; exp: number }>();
  const counters = new Map<string, { c: number; exp: number }>();
  const alive = (e: number, now: number) => e === 0 || e > now;
  return {
    async get(key) {
      const rec = store.get(key);
      if (!rec) return null;
      if (!alive(rec.exp, Date.now())) { store.delete(key); return null; }
      return rec.v;
    },
    async set(key, value, ttlMs) {
      store.set(key, { v: value, exp: ttlMs ? Date.now() + ttlMs : 0 });
    },
    async del(key) { store.delete(key); },
    async incrWindow(key, windowMs, now = Date.now()) {
      const bucket = Math.floor(now / windowMs);
      const k = `${key}:${bucket}`;
      const cur = counters.get(k);
      if (cur && alive(cur.exp, now)) { cur.c += 1; return cur.c; }
      counters.set(k, { c: 1, exp: now + windowMs });
      return 1;
    },
  };
}

// ── Vercel KV (Upstash Redis REST) 어댑터 — fetch 만 사용 ──────────────────
export function createRestKV(url: string, token: string): KVStore {
  async function cmd(...args: (string | number)[]): Promise<unknown> {
    const res = await fetch(`${url}/${args.map((a) => encodeURIComponent(String(a))).join("/")}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error(`KV ${args[0]} 실패: ${res.status}`);
    const data = (await res.json()) as { result?: unknown };
    return data.result;
  }
  return {
    async get(key) {
      const r = await cmd("GET", key);
      return r == null ? null : String(r);
    },
    async set(key, value, ttlMs) {
      if (ttlMs) await cmd("SET", key, value, "PX", ttlMs);
      else await cmd("SET", key, value);
    },
    async del(key) { await cmd("DEL", key); },
    async incrWindow(key, windowMs, now = Date.now()) {
      const bucket = Math.floor(now / windowMs);
      const k = `${key}:${bucket}`;
      const c = Number(await cmd("INCR", k));
      if (c === 1) await cmd("PEXPIRE", k, windowMs); // 창 첫 진입에만 TTL
      return c;
    },
  };
}

// env 로 자동 선택 — KV_REST_API_URL/TOKEN 있으면 운영 KV, 없으면 인메모리
let _singleton: KVStore | null = null;
export function resolveKV(): KVStore {
  if (_singleton) return _singleton;
  const url = process.env.KV_REST_API_URL;
  const token = process.env.KV_REST_API_TOKEN;
  _singleton = url && token ? createRestKV(url, token) : createMemoryKV();
  return _singleton;
}
