// 이메일 → 접근 레벨 (docs/05-auth.md §3.2.1, §4.12.2)
//   L1 = 사내 도메인 이메일 · L2 = L1 + 이메일 허용목록(admin)
// 실제 값은 환경변수로 주입한다. 여기 기본값은 개발용.
import type { Level } from "./levels.ts";

function csv(v: string | undefined, fallback: string): string[] {
  return (v ?? fallback)
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
}

export function allowedDomains(): string[] {
  return csv(process.env.ALLOWED_EMAIL_DOMAINS, "poscofuturem.com,posco.com");
}

export function l2AdminEmails(): string[] {
  return csv(process.env.L2_ADMIN_EMAILS, "");
}

export function normalizeEmail(email: string): string {
  return (email || "").trim().toLowerCase();
}

export function domainOf(email: string): string {
  const at = email.lastIndexOf("@");
  return at >= 0 ? email.slice(at + 1) : "";
}

export function emailDomainAllowed(email: string): boolean {
  return allowedDomains().includes(domainOf(normalizeEmail(email)));
}

// 이메일이 받을 레벨. 자격 없으면 null → 코드 발급 거부 (fail-closed).
export function levelForEmail(email: string): Level | null {
  const e = normalizeEmail(email);
  if (l2AdminEmails().includes(e)) return "L2"; // 허용목록은 도메인 무관하게 L2
  if (emailDomainAllowed(e)) return "L1";
  return null;
}
