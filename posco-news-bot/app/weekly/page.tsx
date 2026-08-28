"use client";
import { useEffect, useState } from "react";

// /weekly/ — 주간 브리프 + outlook (L2 전용). likely·monitoring 은 여기서만 본다.
interface OutlookItem { text?: string; event?: string; action?: string; basis?: string[]; confidence?: string; }
interface Weekly {
  week: string;
  counts?: Record<string, unknown>;
  key_issues?: string[];
  outlook?: { scheduled?: OutlookItem[]; likely?: OutlookItem[]; monitoring?: OutlookItem[]; recommended_actions?: string[] };
}

export default function WeeklyPage() {
  const [w, setW] = useState<Weekly | null>(null);
  const [status, setStatus] = useState<"loading" | "ok" | "forbidden">("loading");

  useEffect(() => {
    fetch("/api/weekly").then((r) => {
      if (r.status === 403) { setStatus("forbidden"); return null; }
      return r.json();
    }).then((d) => { if (d) { setW(d); setStatus("ok"); } }).catch(() => setStatus("forbidden"));
  }, []);

  if (status === "loading") return <div className="wrap"><p className="note">불러오는 중…</p></div>;
  if (status === "forbidden")
    return <div className="wrap"><h1 className="title">🔒 주간 브리프</h1>
      <p className="err">L2(대외협력) 권한이 필요합니다.</p></div>;

  const o = w?.outlook || {};
  return (
    <div className="wrap">
      <h1 className="title">🗓️ 주간 브리프 {w?.week}</h1>
      <section className="card">
        <h2>향후 전망 (outlook)</h2>
        <p className="meta">확정 일정</p>
        <ul className="bullets">
          {(o.scheduled || []).map((it, i) => <li key={i}>{it.date ? `${it.date} · ` : ""}{it.event} → {it.action}</li>)}
          {!(o.scheduled || []).length && <li className="note">—</li>}
        </ul>
        <p className="meta">유력 전개 (근거 기사 필수)</p>
        <ul className="bullets">
          {(o.likely || []).map((it, i) => <li key={i}>{it.text} <span className="conf">(근거 {it.basis?.length || 0})</span></li>)}
          {!(o.likely || []).length && <li className="note">—</li>}
        </ul>
        <p className="meta">주시 (근거 약함)</p>
        <ul className="bullets">
          {(o.monitoring || []).map((it, i) => <li key={i}>{it.text}</li>)}
          {!(o.monitoring || []).length && <li className="note">—</li>}
        </ul>
        <p className="meta">권고 액션</p>
        <ul className="bullets">
          {(o.recommended_actions || []).map((a, i) => <li key={i}>{a}</li>)}
          {!(o.recommended_actions || []).length && <li className="note">—</li>}
        </ul>
      </section>
    </div>
  );
}
