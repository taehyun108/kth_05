"use client";
import { useEffect, useState } from "react";

// /swot/ — 이슈 단위 SWOT 4분면 (L2 전용). L1 세션이면 API 가 403 → 안내.
// SWOT 내용은 웹에서만 노출된다(INV-3). 카톡·메일·텔레그램엔 절대 나가지 않는다.
interface SwotItem { text: string; evidence: string[]; confidence: string; }
interface Issue {
  issue_id: string; title: string | null; status: string; baseline: string;
  articles: string[]; swot?: Record<"S" | "W" | "O" | "T", SwotItem[]>;
  strategy?: Record<string, string>;
}

const AXES: { key: "S" | "W" | "O" | "T"; label: string }[] = [
  { key: "S", label: "S 강점 (내부)" },
  { key: "W", label: "W 약점 (내부)" },
  { key: "O", label: "O 기회 (외부)" },
  { key: "T", label: "T 위협 (외부)" },
];

export default function SwotPage() {
  const [issues, setIssues] = useState<Issue[]>([]);
  const [status, setStatus] = useState<"loading" | "ok" | "forbidden">("loading");

  useEffect(() => {
    fetch("/api/issues").then((r) => {
      if (r.status === 403) { setStatus("forbidden"); return null; }
      return r.json();
    }).then((d) => {
      if (d) { setIssues(d.issues || []); setStatus("ok"); }
    }).catch(() => setStatus("forbidden"));
  }, []);

  if (status === "loading") return <div className="wrap"><p className="note">불러오는 중…</p></div>;
  if (status === "forbidden")
    return <div className="wrap"><h1 className="title">🔒 SWOT</h1>
      <p className="err">L2(대외협력) 권한이 필요합니다.</p></div>;

  return (
    <div className="wrap">
      <h1 className="title">🎯 이슈별 SWOT · 기준: 포스코퓨처엠</h1>
      {issues.filter((i) => i.status !== "merged").map((iss) => (
        <section key={iss.issue_id} className="card" style={{ marginBottom: 12 }}>
          <h2>{iss.title || iss.issue_id}</h2>
          <div className="meta">이슈 {iss.issue_id} · 기사 {iss.articles.length}건</div>
          <div className="swot-grid">
            {AXES.map(({ key, label }) => (
              <div key={key} className={`swot-cell swot-${key}`}>
                <strong>{label}</strong>
                <ul className="bullets">
                  {(iss.swot?.[key] || []).map((it, i) => (
                    <li key={i}>{it.text}
                      <span className="conf"> ({it.confidence}{it.evidence.length ? `·근거 ${it.evidence.length}` : "·근거없음"})</span>
                    </li>
                  ))}
                  {(!iss.swot?.[key] || iss.swot[key].length === 0) && <li className="note">—</li>}
                </ul>
              </div>
            ))}
          </div>
        </section>
      ))}
      {issues.length === 0 && <p className="note">생성된 이슈가 없습니다.</p>}
    </div>
  );
}
