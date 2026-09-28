"""
PDF 를 첨부해서 Gmail 로 보내는 모듈.

Gmail SMTP + 앱 비밀번호 방식을 씁니다. (Gmail API 방식은 개인용 앱의 로그인이
7일마다 풀려서 매일 자동 발송에 맞지 않음)
필요한 .env 값: GMAIL_USER(보내는 주소), GMAIL_APP_PASSWORD(16자리), GMAIL_TO(받는 주소)
"""

import smtplib
import time
from email.message import EmailMessage
from html import escape
from pathlib import Path

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465  # SSL


def build_message(results, pdf_path, day, sender, to, subject_prefix):
    """메일을 만든다. 본문에는 글 제목 목록과 원문 링크, 첨부는 PDF."""
    msg = EmailMessage()
    msg["Subject"] = f"{subject_prefix} {day} - {len(results)}개 글"
    msg["From"] = sender
    msg["To"] = to

    # 1) 글자만 보이는 메일 앱용 본문
    lines = [f"Reddit 게임개발 다이제스트 {day}", f"오늘의 글 {len(results)}개 (자세한 내용은 첨부 PDF)", ""]
    for i, r in enumerate(results, 1):
        lines += [
            f"{i}. {r['title_ko']}",
            f"   r/{r['subreddit']} · u/{r['author']} · 유용도 {r['usefulness']}/10",
            f"   {r['permalink']}",
            "",
        ]
    lines.append("개인 학습용 번역입니다. 원문 저작권은 각 작성자에게 있습니다.")
    msg.set_content("\n".join(lines))

    # 2) 보통 메일 앱(Gmail 등)에서 보이는 HTML 본문
    items = "".join(
        f'<li style="margin-bottom:12px">'
        f'<a href="{escape(r["permalink"])}" style="font-weight:bold;color:#1C64F2">{escape(r["title_ko"])}</a><br>'
        f'<span style="color:#666;font-size:13px">r/{escape(r["subreddit"])} · u/{escape(r["author"])}'
        f' · 유용도 {r["usefulness"]}/10 · {escape(", ".join(r["tags"]))}</span><br>'
        f'<span style="font-size:14px">{escape(r["summary"][0]) if r["summary"] else ""}</span></li>'
        for r in results
    )
    html = (
        f'<div style="font-family:sans-serif;max-width:640px">'
        f'<h2 style="margin-bottom:4px">Reddit 게임개발 다이제스트</h2>'
        f'<p style="color:#666;margin-top:0">{day} · 오늘의 글 {len(results)}개 · 자세한 내용은 첨부 PDF</p>'
        f'<ol style="padding-left:20px">{items}</ol>'
        f'<p style="color:#999;font-size:12px">개인 학습용 번역입니다. 원문 저작권은 각 작성자에게 있습니다.</p>'
        f'</div>'
    )
    msg.add_alternative(html, subtype="html")

    # 3) PDF 첨부
    pdf_path = Path(pdf_path)
    msg.add_attachment(pdf_path.read_bytes(), maintype="application", subtype="pdf", filename=pdf_path.name)
    return msg


def send(msg, user, app_password, retries=2):
    """Gmail SMTP 로 메일을 보낸다. 네트워크 문제면 잠시 후 다시 시도."""
    for attempt in range(retries + 1):
        try:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=60) as smtp:
                smtp.login(user, app_password.replace(" ", ""))  # 앱 비밀번호의 띄어쓰기는 무시
                smtp.send_message(msg)
            return
        except smtplib.SMTPAuthenticationError:
            # 비밀번호가 틀린 경우는 다시 시도해도 소용없으므로 바로 알림
            raise RuntimeError("Gmail 로그인 실패: .env 의 GMAIL_USER / GMAIL_APP_PASSWORD 를 확인하세요.")
        except (smtplib.SMTPException, OSError):
            if attempt == retries:
                raise
            time.sleep(5 * (2 ** attempt))
