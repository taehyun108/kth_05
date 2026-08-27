import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "포스코 뉴스 브리핑",
  description: "포스코 그룹·이차전지·정책·통상 뉴스 아카이브",
};

// 모바일 대응 (docs/04-frontend.md §4.6.3) — 뷰포트 고정
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
