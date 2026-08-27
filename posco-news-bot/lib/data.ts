// data/ 읽기 — 서버에서만. public/ 에 두지 않는다 (INV-8).
//   실제 파일(<name>.json)이 없으면 개발용 시드(<name>.sample.json)로 폴백.
import fs from "node:fs";
import path from "node:path";

export function dataDir(): string {
  return process.env.PNB_DATA_DIR || path.join(process.cwd(), "data");
}

export function readDataFile(name: string, dir?: string): Record<string, unknown> {
  const base = dir || dataDir();
  const candidates = [path.join(base, `${name}.json`), path.join(base, `${name}.sample.json`)];
  for (const p of candidates) {
    if (fs.existsSync(p)) {
      return JSON.parse(fs.readFileSync(p, "utf8")) as Record<string, unknown>;
    }
  }
  throw new Error(`data file not found: ${name} (looked in ${base})`);
}
