"use client";
import { useEffect, useMemo, useState } from "react";
import { POLICY_STAGE } from "../../lib/taxonomy.ts";

// /policy/ — 국가 × 이슈 보드 + 정책 타임라인 (L1 board / L2 full).
interface TimelineEvent { date: string; stage: string; article_ids: string[]; source_type?: string; }
interface Policy {
  policy_id: string; country: string; name: string; issue_tags: string[];
  current_stage: string; timeline: TimelineEvent[]; affects_futurem?: boolean;
}

function stageBadge(stage?: string) {
  const s = stage ? POLICY_STAGE[stage] : undefined;
  return s ? <span className={`badge ${s.cls}`}>{s.label}</span> : <span className="note">—</span>;
}

export default function PolicyPage() {
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [sel, setSel] = useState<Policy | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/policies").then((r) => (r.ok ? r.json() : { policies: [] }))
      .then((d) => setPolicies(d.policies || [])).finally(() => setLoading(false));
  }, []);

  const { countries, issues, cell } = useMemo(() => {
    const countries = [...new Set(policies.map((p) => p.country))];
    const issues = [...new Set(policies.flatMap((p) => p.issue_tags || [p.name]))];
    const cell: Record<string, Policy> = {};
    for (const p of policies) for (const iss of (p.issue_tags || [p.name])) cell[`${p.country}|${iss}`] = p;
    return { countries, issues, cell };
  }, [policies]);

  if (loading) return <div className="wrap"><p className="note">불러오는 중…</p></div>;

  return (
    <div className="wrap">
      <h1 className="title">📜 정책 현황 보드 (국가 × 이슈)</h1>
      <div style={{ overflowX: "auto" }}>
        <table className="board">
          <thead><tr><th></th>{issues.map((i) => <th key={i}>{i}</th>)}</tr></thead>
          <tbody>
            {countries.map((c) => (
              <tr key={c}>
                <th>{c}</th>
                {issues.map((i) => {
                  const p = cell[`${c}|${i}`];
                  return <td key={i} onClick={() => p && setSel(p)} style={{ cursor: p ? "pointer" : "default" }}>
                    {p ? stageBadge(p.current_stage) : ""}
                    {p?.affects_futurem ? " 🔴" : ""}
                  </td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {sel && (
        <section className="card" style={{ marginTop: 12 }}>
          <h2>{sel.country} · {sel.name} 타임라인</h2>
          <ul className="bullets">
            {sel.timeline.map((e, i) => (
              <li key={i}>{e.date} {stageBadge(e.stage)}
                <span className="conf"> {e.source_type ? `· ${e.source_type}` : ""} · 근거 {e.article_ids.length}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {policies.length === 0 && <p className="note">정책 데이터가 없습니다.</p>}
    </div>
  );
}
