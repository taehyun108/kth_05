/** @type {import('next').NextConfig} */
const nextConfig = {
  // data/ 는 서버에서만 fs 로 읽는다 — public/ 에 두지 않는다 (INV-8).
  reactStrictMode: true,
};

export default nextConfig;
