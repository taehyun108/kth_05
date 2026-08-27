// 로그인 코드 발송 (스텁). 실제 SMTP 연동은 P5c(s7_mail) 자산을 재사용한다.
//   개발/미설정 환경에서는 서버 로그로만 남긴다 (응답 본문엔 절대 넣지 않는다).
export async function sendLoginCode(email: string, code: string): Promise<void> {
  if (process.env.SMTP_URL) {
    // TODO(P5c): 실제 SMTP 발송. 여기서는 구조만 잡아둔다.
    console.log(`[mailer] (SMTP) 로그인 코드 발송 → ${email}`);
    return;
  }
  // 개발: 코드가 메일로 나가지 않으므로 서버 콘솔에만 출력
  console.log(`[mailer] DEV login code for ${email}: ${code} (10분 만료)`);
}
