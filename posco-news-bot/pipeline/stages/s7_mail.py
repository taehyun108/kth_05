"""s7_mail — 일일 브리핑 메일 (docs/07-mail.md). Part A 언론 클리핑 + Part B 정책·통상.

🔒 INV-7: 이 파일은 비공개 분석 산출물을 import 하지 않는다 (CI grep 대상).
           공개 기사(analyzed/l1)만 입력으로 받는다.
🔒 INV-9: 링크를 한 번도 안 눌러도 업무가 되게 — bullets 를 본문에 전개하고,
           정책·분쟁 단계를 텍스트 배지로 넣고, 링크는 언론사 원문 우선.
🔒 INV-6: 논조(tone)가 없으면(L0 단독) 논조 열과 매체별 대비를 빼고
           "언론사별 보도 목록"으로 발송한다. 제목에 (요약본) 표기. 메일을 거르지 않는다.
"""
from __future__ import annotations

import abc
import html as _html
import json
from pathlib import Path
from typing import Any, Iterable

from . import common

TONE_LABEL = {"positive": "🟢긍정", "neutral": "⚪중립", "negative": "🔴부정", "crisis": "🚨위기"}
POLICY_STAGE_LABEL = {"discussion": "논의", "proposed": "예고", "enacted": "확정",
                      "effective": "시행", "amended": "개정"}
DISPUTE_STAGE_LABEL = {"initiated": "조사개시", "preliminary": "예비판정", "final": "최종판정",
                       "in_force": "발효", "negotiating": "협상중", "terminated": "종료"}
COUNTRY_FLAG = {"KR": "🇰🇷", "US": "🇺🇸", "EU": "🇪🇺", "CN": "🇨🇳", "JP": "🇯🇵",
                "CA": "🇨🇦", "AU": "🇦🇺", "IN": "🇮🇳", "ID": "🇮🇩"}
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

VERCEL_LABEL = "전체보기(로그인)"


# ── 선별 (docs §4.11.2 Part A/B 구분) ───────────────────────────────────────

def select_part_a(articles: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """포스코 언론 클리핑 — posco_relevance ∈ {primary, mention}."""
    return [a for a in articles if a.get("posco_relevance") in ("primary", "mention")]


def select_part_b(articles: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """정책·통상 (포스코 미언급 + impact≥mid) — 카톡에 안 가는, 메일 전용 내용."""
    return [a for a in articles
            if a.get("track") in ("policy", "trade")
            and a.get("posco_relevance") == "none"
            and a.get("impact") in ("high", "mid")]


def has_tone(articles: Iterable[dict[str, Any]]) -> bool:
    return any(a.get("tone") for a in articles)


# ── 그룹핑 ───────────────────────────────────────────────────────────────────

def group_by_outlet(articles: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for a in articles:
        groups.setdefault(a.get("outlet") or "기타", []).append(a)
    return sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))


def attention_items(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """주의 필요 — 위기 > 부정 순."""
    rank = {"crisis": 0, "negative": 1}
    items = [a for a in articles if a.get("tone") in ("crisis", "negative")]
    return sorted(items, key=lambda a: rank.get(a.get("tone"), 9))


def media_contrast(articles: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """동일 issue_id 에 2개 이상 매체가 붙었을 때만 (docs §4.11.2 ④)."""
    by_issue: dict[str, list[dict[str, Any]]] = {}
    for a in articles:
        iid = a.get("issue_id")
        if iid:
            by_issue.setdefault(iid, []).append(a)
    out = []
    for iid, arts in by_issue.items():
        outlets = {a.get("outlet") for a in arts}
        if len(outlets) >= 2:
            out.append((iid, arts))
    return out


def part_b_groups(articles: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for a in articles:
        groups.setdefault(f"{a.get('track')}/{a.get('category')}", []).append(a)
    # 통상(trade) 먼저, 그다음 정책(policy)
    return sorted(groups.items(), key=lambda kv: (0 if kv[0].startswith("trade") else 1, kv[0]))


# ── 통계·라벨 ────────────────────────────────────────────────────────────────

def tone_counts(articles: list[dict[str, Any]]) -> dict[str, int]:
    acc = {"positive": 0, "neutral": 0, "negative": 0, "crisis": 0}
    for a in articles:
        t = a.get("tone")
        if t in acc:
            acc[t] += 1
    return acc


def stage_badge(a: dict[str, Any]) -> str:
    ps = a.get("policy_stage")
    ds = a.get("dispute_stage")
    if ds and ds in DISPUTE_STAGE_LABEL:
        return f"[{DISPUTE_STAGE_LABEL[ds]}]"
    if ps and ps in POLICY_STAGE_LABEL:
        return f"[{POLICY_STAGE_LABEL[ps]}]"
    return ""


def flag(a: dict[str, Any]) -> str:
    cs = a.get("countries") or []
    return " ".join(COUNTRY_FLAG.get(c, c) for c in cs)


def fmt_date(d: str | None, now) -> str:
    dt = common.parse_dt(d) or now
    return f"{dt.month}/{dt.day}({WEEKDAYS[dt.weekday()]})"


# ── 본문 빌더 (텍스트 + HTML) ────────────────────────────────────────────────

def _bullets_text(a: dict[str, Any]) -> str:
    # INV-9: 요약 + bullets 를 본문에 전개 (링크 안 눌러도 업무가 되게)
    lines = [a.get("summary", "")]
    for b in (a.get("bullets") or [])[:5]:
        lines.append(f"    · {b}")
    return "\n".join(x for x in lines if x)


def build_mail(articles: list[dict[str, Any]], now=None, base_url: str = "") -> dict[str, Any]:
    now = now or common.now_kst()
    part_a = select_part_a(articles)
    part_b = select_part_b(articles)
    tone_on = has_tone(part_a)
    tc = tone_counts(part_a)

    # 제목 (docs §4.11.2) — 논조 없으면 (요약본)
    suffix = "" if tone_on else " (요약본)"
    subject = (f"[포스코 브리핑] {fmt_date(None, now)} 포스코 {len(part_a)}건 · 정책통상 {len(part_b)}건"
               + (f" · 부정 {tc['negative']} · 위기 {tc['crisis']}" if tone_on else "") + suffix)

    text = _render_text(part_a, part_b, tone_on, tc, now, base_url)
    html = _render_html(part_a, part_b, tone_on, tc, now, base_url)
    return {
        "subject": subject, "text": text, "html": html,
        "meta": {"part_a": len(part_a), "part_b": len(part_b), "tone": tone_on,
                 "outlets": len({a.get("outlet") for a in part_a})},
    }


def _link(a: dict[str, Any], base_url: str) -> str:
    # 원문 링크 우선. Vercel 링크는 "전체보기(로그인)" 로 명시(INV-9 §3.3.3)
    url = a.get("url") or ""
    parts = [f"🔗 원문 {url}" if url else ""]
    if base_url and a.get("id"):
        parts.append(f"{VERCEL_LABEL} {base_url}/posco/articles/{a['id']}")
    return "  ".join(p for p in parts if p)


def _render_text(part_a, part_b, tone_on, tc, now, base_url) -> str:
    L: list[str] = []
    L.append(f"[포스코 뉴스클리핑] {fmt_date(None, now)}  포스코 {len(part_a)}건 / 정책·통상 {len(part_b)}건")
    if not tone_on:
        L.append("※ 논조 미확정 — 언론사별 보도 목록 (요약본)")
    L.append("")
    # ① 요약 통계
    outlets = len({a.get("outlet") for a in part_a})
    L.append(f"① 요약  총 {len(part_a)}건 · 언론사 {outlets}곳")
    if tone_on:
        L.append(f"   {TONE_LABEL['positive']} {tc['positive']}  {TONE_LABEL['neutral']} {tc['neutral']}"
                 f"  {TONE_LABEL['negative']} {tc['negative']}  {TONE_LABEL['crisis']} {tc['crisis']}")
    # ② 주의 필요 (tone 있을 때만)
    if tone_on:
        att = attention_items(part_a)
        if att:
            L.append("")
            L.append("② 주의 필요 (부정·위기 우선)")
            for a in att:
                L.append(f"  {TONE_LABEL.get(a.get('tone'),'')} {a.get('outlet','')} | {a.get('title','')}")
                L.append(f"    {a.get('summary','')}")
                L.append(f"    {_link(a, base_url)}")
    # ③ 언론사별 보도 내역 (핵심)
    L.append("")
    L.append("③ 언론사별 보도 내역")
    for outlet, arts in group_by_outlet(part_a):
        badge = ""
        if tone_on:
            c = tone_counts(arts)
            badge = f"  {TONE_LABEL['positive']}{c['positive']} {TONE_LABEL['neutral']}{c['neutral']} {TONE_LABEL['negative']}{c['negative']} {TONE_LABEL['crisis']}{c['crisis']}"
        L.append(f"▸ {outlet} ({len(arts)}건){badge}")
        for a in arts:
            cat = a.get("category", "")
            L.append(f"  · [{cat}] {a.get('title','')}")
            L.append(f"    {_bullets_text(a)}")
            L.append(f"    {_link(a, base_url)}")
    # ④ 동일 사안 매체별 대비 (tone 있고 issue_id 2+매체일 때만)
    if tone_on:
        mc = media_contrast(part_a)
        if mc:
            L.append("")
            L.append("④ 동일 사안 매체별 대비")
            for iid, arts in mc:
                title = arts[0].get("title", iid)
                pairs = " / ".join(f"{a.get('outlet','')} {TONE_LABEL.get(a.get('tone'),'')}" for a in arts)
                L.append(f"  「{title}」 — {len(arts)}개 매체")
                L.append(f"    {pairs}")
    # ── Part B ──
    L.append("")
    L.append("=" * 40)
    L.append(f"PART B. 정책·통상 브리핑 (포스코 미언급 · {len(part_b)}건)")
    L.append("=" * 40)
    for key, arts in part_b_groups(part_b):
        L.append(f"[{key}]")
        for a in arts:
            L.append(f"  {flag(a)} {stage_badge(a)} {a.get('title','')}")
            if a.get("affects_futurem"):
                L.append("    ※ 퓨처엠 취급 품목 해당")
            L.append(f"    {_bullets_text(a)}")
            L.append(f"    {_link(a, base_url)}")
    L.append("")
    if base_url:
        L.append(f"전체 아카이브 {VERCEL_LABEL}: {base_url}/posco/")
        L.append(f"정책·통상 상세 {VERCEL_LABEL}: {base_url}/policy/")
    L.append("※ 본 메일은 자동 생성된 언론 모니터링 자료입니다.")
    return "\n".join(L)


def _esc(s: Any) -> str:
    return _html.escape(str(s or ""))


def _render_html(part_a, part_b, tone_on, tc, now, base_url) -> str:
    H: list[str] = ['<div style="font-family:system-ui,sans-serif;max-width:680px;margin:0 auto;color:#1a1d21">']
    H.append(f'<h2>[포스코 뉴스클리핑] {_esc(fmt_date(None, now))} '
             f'<span style="font-weight:400;font-size:0.9rem">포스코 {len(part_a)}건 / 정책·통상 {len(part_b)}건</span></h2>')
    if not tone_on:
        H.append('<p style="color:#b54708">※ 논조 미확정 — 언론사별 보도 목록 (요약본)</p>')
    outlets = len({a.get("outlet") for a in part_a})
    H.append(f'<div style="background:#f6f7f9;border-radius:8px;padding:10px"><b>① 요약</b> 총 {len(part_a)}건 · 언론사 {outlets}곳')
    if tone_on:
        H.append(f'<br>{TONE_LABEL["positive"]} {tc["positive"]} &nbsp; {TONE_LABEL["neutral"]} {tc["neutral"]}'
                 f' &nbsp; {TONE_LABEL["negative"]} {tc["negative"]} &nbsp; {TONE_LABEL["crisis"]} {tc["crisis"]}')
    H.append("</div>")

    if tone_on:
        att = attention_items(part_a)
        if att:
            H.append('<h3>② 주의 필요 (부정·위기 우선)</h3><ul>')
            for a in att:
                H.append(f'<li>{TONE_LABEL.get(a.get("tone"),"")} <b>{_esc(a.get("outlet"))}</b> | {_esc(a.get("title"))}'
                         f'<br><span style="color:#555">{_esc(a.get("summary"))}</span> {_html_link(a, base_url)}</li>')
            H.append("</ul>")

    H.append("<h3>③ 언론사별 보도 내역</h3>")
    for outlet, arts in group_by_outlet(part_a):
        badge = ""
        if tone_on:
            c = tone_counts(arts)
            badge = f' <span style="color:#6b7280">{TONE_LABEL["negative"]}{c["negative"]} {TONE_LABEL["crisis"]}{c["crisis"]}</span>'
        H.append(f'<p style="margin:8px 0 4px"><b>▸ {_esc(outlet)}</b> ({len(arts)}건){badge}</p><ul>')
        for a in arts:
            H.append(f'<li>[{_esc(a.get("category"))}] <b>{_esc(a.get("title"))}</b>'
                     f'<br><span style="color:#333">{_esc(a.get("summary"))}</span>')
            if a.get("bullets"):
                H.append("<ul>" + "".join(f"<li>{_esc(b)}</li>" for b in a["bullets"][:5]) + "</ul>")
            H.append(f'<div style="font-size:0.85rem">{_html_link(a, base_url)}</div></li>')
        H.append("</ul>")

    if tone_on:
        mc = media_contrast(part_a)
        if mc:
            H.append("<h3>④ 동일 사안 매체별 대비</h3><ul>")
            for iid, arts in mc:
                pairs = " / ".join(f'{_esc(a.get("outlet"))} {TONE_LABEL.get(a.get("tone"),"")}' for a in arts)
                H.append(f'<li>「{_esc(arts[0].get("title"))}」 — {len(arts)}개 매체<br>{pairs}</li>')
            H.append("</ul>")

    H.append('<hr><h2>PART B · 정책·통상 브리핑 '
             f'<span style="font-weight:400;font-size:0.9rem">(포스코 미언급 · {len(part_b)}건)</span></h2>')
    for key, arts in part_b_groups(part_b):
        H.append(f"<h3>{_esc(key)}</h3><ul>")
        for a in arts:
            note = ' <span style="color:#b54708">※ 퓨처엠 취급 품목</span>' if a.get("affects_futurem") else ""
            H.append(f'<li>{flag(a)} <b>{_esc(stage_badge(a))} {_esc(a.get("title"))}</b>{note}'
                     f'<br><span style="color:#333">{_esc(a.get("summary"))}</span>')
            if a.get("bullets"):
                H.append("<ul>" + "".join(f"<li>{_esc(b)}</li>" for b in a["bullets"][:5]) + "</ul>")
            H.append(f'<div style="font-size:0.85rem">{_html_link(a, base_url)}</div></li>')
        H.append("</ul>")

    if base_url:
        H.append(f'<p style="font-size:0.85rem"><a href="{_esc(base_url)}/posco/">{VERCEL_LABEL}: 전체 아카이브</a> · '
                 f'<a href="{_esc(base_url)}/policy/">{VERCEL_LABEL}: 정책·통상</a></p>')
    H.append('<p style="color:#6b7280;font-size:0.8rem">※ 본 메일은 자동 생성된 언론 모니터링 자료입니다.</p></div>')
    return "\n".join(H)


def _html_link(a: dict[str, Any], base_url: str) -> str:
    url = a.get("url") or ""
    out = []
    if url:
        out.append(f'<a href="{_esc(url)}">🔗 원문</a>')
    if base_url and a.get("id"):
        out.append(f'<a href="{_esc(base_url)}/posco/articles/{_esc(a["id"])}">{VERCEL_LABEL}</a>')
    return " · ".join(out)


# ── SMTP 어댑터 (인터페이스만; 자격증명 없으면 파일 출력) ────────────────────

class MailSender(abc.ABC):
    @abc.abstractmethod
    def send(self, subject: str, text: str, html: str, to: str) -> bool: ...


class FileMailSender(MailSender):
    """SMTP 미설정 시 — 메일을 파일로 떨어뜨려 확인 가능하게(발송하지 않음)."""

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.sent: list[dict[str, str]] = []

    def send(self, subject: str, text: str, html: str, to: str) -> bool:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        stem = self.out_dir / f"mail-{common.now_kst().strftime('%Y%m%d-%H%M%S')}"
        (stem.with_suffix(".txt")).write_text(f"To: {to}\nSubject: {subject}\n\n{text}", encoding="utf-8")
        (stem.with_suffix(".html")).write_text(html, encoding="utf-8")
        self.sent.append({"to": to, "subject": subject})
        return True


class SmtpMailSender(MailSender):
    """실제 SMTP 발송 — 자격증명은 env. 이미지·첨부 없음, HTML+텍스트 멀티파트."""

    def __init__(self, host: str, port: int, user: str, password: str) -> None:
        self.host, self.port, self.user, self.password = host, port, user, password

    def send(self, subject: str, text: str, html: str, to: str) -> bool:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.user
        msg["To"] = to
        msg["List-Id"] = "posco-news.internal"           # 자동 발송 명시(도달률, docs §4.11.6)
        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP(self.host, self.port) as s:
            s.starttls()
            s.login(self.user, self.password)
            s.sendmail(self.user, [to], msg.as_string())
        return True


def resolve_sender(out_dir: Path) -> MailSender:
    import os
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    pw = os.environ.get("SMTP_PASS")
    if host and user and pw:
        return SmtpMailSender(host, int(os.environ.get("SMTP_PORT", "587")), user, pw)
    return FileMailSender(out_dir)     # 미설정 → 파일로


# ── 실행 ─────────────────────────────────────────────────────────────────────

def run(run_id: str, base_dir: Path | None = None, *, to: str | None = None,
        base_url: str = "", out_dir: Path | None = None) -> dict[str, Any]:
    base = base_dir or (common.ROOT / "raw")
    src = base / run_id / "l1.jsonl"
    if not src.exists():
        src = base / run_id / "analyzed.jsonl"
    articles = list(common.read_jsonl(src)) if src.exists() else []

    mail = build_mail(articles, base_url=base_url)
    import os
    recipient = to or os.environ.get("MAIL_TO_GROUP", "posco-team@example.internal")
    sender = resolve_sender(out_dir or (base / run_id / "mail"))
    ok = sender.send(mail["subject"], mail["text"], mail["html"], recipient)
    print(f"[s7_mail] {mail['subject']} → {recipient} ({'sent' if ok else 'fail'}) · "
          f"{type(sender).__name__}")
    return {"subject": mail["subject"], "meta": mail["meta"], "sent": ok,
            "sender": type(sender).__name__}
