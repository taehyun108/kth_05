// 완료기준 ⑤ 모바일 정상 — 뷰포트 + pill 폭발 방지 + facets 필터
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import fs from "node:fs";
import path from "node:path";
import { visiblePills, articleMatches, filterArticles } from "../../lib/facets.ts";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

test("완료기준⑤: 레이아웃에 반응형 뷰포트가 설정돼 있다", () => {
  const layout = fs.readFileSync(path.join(ROOT, "app/layout.tsx"), "utf8");
  assert.match(layout, /width:\s*"device-width"/);
  const css = fs.readFileSync(path.join(ROOT, "app/globals.css"), "utf8");
  assert.match(css, /@media\s*\(min-width/); // 모바일 1열 → 넓으면 2열
});

test("완료기준⑤: pill 폭발 방지 — 트랙 미선택 시 트랙만, 선택 시 그 트랙 카테고리만", () => {
  const top = visiblePills(null);
  assert.equal(top.kind, "tracks");
  assert.deepEqual(top.items, ["posco", "battery", "policy", "trade"]); // 최대 4개

  const drill = visiblePills("posco");
  assert.equal(drill.kind, "categories");
  assert.ok(drill.items.includes("futurem"));
  assert.ok(drill.items.every((c) => ["holdings", "posco-steel", "futurem", "international", "enc", "dx", "group"].includes(c)));
  assert.ok(!drill.items.includes("cell-kr")); // 다른 트랙 카테고리 미노출
});

test("facets 필터: 그룹 간 AND, 그룹 내 OR", () => {
  const arts = [
    { facets: ["track:posco", "cat:futurem", "country:KR"] },
    { facets: ["track:battery", "cat:cell-kr", "country:EU"] },
    { facets: ["track:policy", "cat:pol-us", "country:US"] },
  ];
  // 트랙 그룹 OR (posco 또는 battery)
  assert.equal(filterArticles(arts, ["track:posco", "track:battery"]).length, 2);
  // 그룹 간 AND (posco AND country:KR)
  assert.equal(filterArticles(arts, ["track:posco", "country:KR"]).length, 1);
  assert.equal(filterArticles(arts, ["track:posco", "country:US"]).length, 0);
  // 선택 없으면 전체
  assert.equal(filterArticles(arts, []).length, 3);
  assert.equal(articleMatches(["track:posco"], []), true);
});
