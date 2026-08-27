"use client";
import { useState } from "react";

// 로그인 코드 흐름 (docs/05-auth.md §4.12.2~3): 이메일 → 코드 발급 → 코드 입력 → next 복귀.
export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [stage, setStage] = useState<"email" | "code">("email");
  const [err, setErr] = useState("");

  function nextParam(): string {
    if (typeof window === "undefined") return "/posco/";
    return new URLSearchParams(window.location.search).get("next") || "/posco/";
  }

  async function requestCode() {
    setErr("");
    const r = await fetch("/api/auth/request", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email }),
    });
    if (r.ok) setStage("code");
    else setErr("코드 발급에 실패했습니다.");
  }

  async function verify() {
    setErr("");
    const r = await fetch("/api/auth/verify", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, code, next: nextParam() }),
    });
    const data = await r.json();
    if (r.ok && data.ok) {
      window.location.href = data.next || "/posco/";
    } else {
      setErr("코드가 올바르지 않거나 만료되었습니다.");
    }
  }

  return (
    <div className="login-box">
      <h1 className="title">포스코 뉴스 브리핑 로그인</h1>
      {stage === "email" ? (
        <>
          <p className="note">사내 이메일을 입력하면 6자리 코드를 보내드립니다.</p>
          <input
            type="email"
            placeholder="name@poscofuturem.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <button onClick={requestCode}>코드 받기</button>
        </>
      ) : (
        <>
          <p className="note">메일로 받은 6자리 코드를 입력하세요. (10분 만료)</p>
          <input
            inputMode="numeric"
            maxLength={6}
            placeholder="123456"
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
          <button onClick={verify}>로그인</button>
        </>
      )}
      {err && <p className="err">{err}</p>}
    </div>
  );
}
