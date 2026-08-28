"use client";
import { useEffect, useMemo, useState } from "react";
import { DISPUTE_STAGE } from "../../lib/taxonomy.ts";

// /trade/ — 부과국 × 대상국 분쟁 보드 + 타임라인 (L1 board / L2 full).
interface TimelineEvent { date: string; stage: string; rate?: string; article_ids: string[]; }
interface Dispute {
  dispute_id: string; imposing_country: string; target_country: string; measure_type: string;
  current_stage: string; current_rate?: string; timeline: TimelineEvent[]; affects_futurem?: boolean;
}

function stageBadge(stage?: string) {
  const s = stage ? DISPUTE_STAGE[stage] : undefined;
  return s ? <span className={`badge ${s.cls}`}>{s.label}</span> : <span className="note">—</span>;
}

export default function TradePage() {
  const [disputes, setDisputes] = useState<Dispute[]>([]);
  const [sel, setSel] = useState<Dispute | null>(null);
  const [onlyAffects, setOnlyAffects] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/disputes").then((r) => (r.ok ? r.json() : { disputes: [] }))
      .then((d) => setDisputes(d.disputes || [])).finally(() => setLoading(false));
  }, []);

  const shown = useMemo(
    () => (onlyAffects ? disputes.filter((d) => d.affects_futurem) : disputes),
    [disputes, onlyAffects]
  );
  const { imposers, targets, cell } = useMemo(() => {
    const imposers = [...new Set(shown.map((d) => d.imposing_country))];
    const targets = [...new Set(shown.map((d) => d.target_country))];
    const cell: Record<string, Dispute> = {};
    for (const d of shown) cell[`${d.imposing_country}|${d.target_country}`] = d;
    return { imposers, targets, cell };
  }, [shown]);

  if (loading) return <div className="wrap"><p className="note">불러오는 중…</p></div>;

  return (
    <div className="wrap">
      <h1 className="title">⚔️ 분쟁 현황 보드 (부과국 × 대상국)</h1>
      <label className="note" style={{ display: "block", margin: "6px 0" }}>
        <input type="checkbox" checked={onlyAffects} onChange={(e) => setOnlyAffects(e.target.checked)} />
        {" "}퓨처엠 취급 품목만 (affects_futurem){disputes.some((d) => "affects_futurem" in d) ? "" : " — L2 세션 필요"}
      </label>
      <div style={{ overflowX: "auto" }}>
        <table className="board">
          <thead><tr><th>부과국\대상국</th>{targets.map((t) => <th key={t}>{t}</th>)}</tr></thead>
          <tbody>
            {imposers.map((im) => (
              <tr key={im}>
                <th>{im}</th>
                {targets.map((t) => {
                  const d = cell[`${im}|${t}`];
                  return <td key={t} onClick={() => d && setSel(d)} style={{ cursor: d ? "pointer" : "default" }}>
                    {d ? stageBadge(d.current_stage) : ""}{d?.current_rate ? ` ${d.current_rate}` : ""}
                    {d?.affects_futurem ? " 🔴" : ""}
                  </td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {sel && (
        <section className="card" style={{ marginTop: 12 }}>
          <h2>{sel.imposing_country} → {sel.target_country} · {sel.measure_type} 타임라인</h2>
          <ul className="bullets">
            {sel.timeline.map((e, i) => (
              <li key={i}>{e.date} {stageBadge(e.stage)}{e.rate ? ` ${e.rate}` : ""}
                <span className="conf"> · 근거 {e.article_ids.length}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {disputes.length === 0 && <p className="note">분쟁 데이터가 없습니다.</p>}
    </div>
  );
}
