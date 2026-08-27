"use client";
import { useEffect, useMemo, useState } from "react";
import { TRACKS, CATEGORIES } from "../../lib/taxonomy.ts";
import type { TrackId } from "../../lib/taxonomy.ts";
import { visiblePills, filterArticles } from "../../lib/facets.ts";
import { toCardView } from "../../lib/card.ts";
import type { Article } from "../../lib/card.ts";

// /posco/ — T1+T2 아카이브. 트랙 토글 + facets 필터 + 카드 그리드 (docs §4.6.3~4).
// L1/L2 필드는 서버가 걸러 보낸다. 화면은 응답에 있는 것만 그린다(INV-8/INV-6).
export default function PoscoPage() {
  const [articles, setArticles] = useState<Article[]>([]);
  const [activeTrack, setActiveTrack] = useState<TrackId | null>(null);
  const [activeFacets, setActiveFacets] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/articles")
      .then((r) => (r.ok ? r.json() : { articles: [] }))
      .then((d) => setArticles(d.articles || []))
      .finally(() => setLoading(false));
  }, []);

  function toggleTrack(t: TrackId) {
    if (activeTrack === t) {
      setActiveTrack(null);
      setActiveFacets((f) => f.filter((x) => !x.startsWith("track:") && !x.startsWith("cat:")));
    } else {
      setActiveTrack(t);
      setActiveFacets([`track:${t}`]);
    }
  }

  function toggleCategory(cat: string) {
    const facet = `cat:${cat}`;
    setActiveFacets((f) => (f.includes(facet) ? f.filter((x) => x !== facet) : [...f, facet]));
  }

  const pills = visiblePills(activeTrack);
  const shown = useMemo(() => filterArticles(articles, activeFacets), [articles, activeFacets]);

  return (
    <div className="wrap">
      <header className="app">
        <h1 className="title">📰 포스코 뉴스 브리핑</h1>
      </header>

      {/* 1차 축: 트랙 (미선택 시 트랙 pill만, 선택 시 카테고리 pill) */}
      <div className="pills">
        {pills.kind === "tracks"
          ? pills.items.map((t) => (
              <button
                key={t}
                className={`pill ${activeTrack === t ? "active" : ""}`}
                onClick={() => toggleTrack(t as TrackId)}
              >
                {TRACKS[t as TrackId].emoji} {TRACKS[t as TrackId].label}
              </button>
            ))
          : (
            <>
              <button className="pill active" onClick={() => toggleTrack(activeTrack as TrackId)}>
                ← {TRACKS[activeTrack as TrackId].label}
              </button>
              {pills.items.map((c) => (
                <button
                  key={c}
                  className={`pill ${activeFacets.includes(`cat:${c}`) ? "active" : ""}`}
                  onClick={() => toggleCategory(c)}
                >
                  {CATEGORIES[c].emoji} {CATEGORIES[c].short}
                </button>
              ))}
            </>
          )}
      </div>

      {loading ? (
        <p className="note">불러오는 중…</p>
      ) : (
        <div className="grid">
          {shown.map((a) => {
            const v = toCardView(a);
            return (
              <article className="card" key={v.id}>
                <div className="badges">
                  {v.badges.map((b, i) => (
                    <span key={i} className={`badge ${b.cls}`}>{b.label}</span>
                  ))}
                </div>
                <h2>
                  <a className="headline" href={v.href} target="_blank" rel="noreferrer">
                    {v.title}
                  </a>
                </h2>
                {v.summary && <p className="summary">{v.summary}</p>}
                {v.bullets.length > 0 && (
                  <ul className="bullets">
                    {v.bullets.map((b, i) => (
                      <li key={i}>{b}</li>
                    ))}
                  </ul>
                )}
                <div className="meta">
                  {v.outlet ? `📰 ${v.outlet}` : ""} {v.date ? `· ${v.date}` : ""}
                </div>
                {v.topics.length > 0 && (
                  <div className="topics">{v.topics.map((t) => `#${t}`).join(" ")}</div>
                )}
              </article>
            );
          })}
          {shown.length === 0 && <p className="note">해당 조건의 기사가 없습니다.</p>}
        </div>
      )}
    </div>
  );
}
