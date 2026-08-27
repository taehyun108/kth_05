// 완료기준 ③ public/ 에 데이터 JSON 없음 (INV-8)
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

function walk(dir: string): string[] {
  if (!fs.existsSync(dir)) return [];
  const out: string[] = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...walk(p));
    else out.push(p);
  }
  return out;
}

test("완료기준③: public/ 에 .json 데이터 파일이 없다", () => {
  const jsonFiles = walk(path.join(ROOT, "public")).filter((f) => f.endsWith(".json"));
  assert.deepEqual(jsonFiles, [], `public/ 에 JSON 이 있으면 인증 없이 서빙된다: ${jsonFiles.join(", ")}`);
});

test("데이터 시드는 data/ 아래에만 있다", () => {
  const dataDir = path.join(ROOT, "data");
  const inData = walk(dataDir).filter((f) => f.endsWith(".json"));
  assert.ok(inData.length > 0, "data/ 에 시드가 있어야 함");
  // 그리고 그 어느 것도 public/ 하위 경로가 아니다
  assert.ok(inData.every((f) => !f.includes(`${path.sep}public${path.sep}`)));
});
