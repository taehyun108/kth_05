import { redirect } from "next/navigation";

// 루트 → 아카이브로. 미인증이면 middleware 가 /login 으로 보낸다.
export default function Home() {
  redirect("/posco/");
}
