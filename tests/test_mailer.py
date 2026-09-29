"""
5단계(Gmail) 테스트. 실제로 메일을 보내지 않도록 SMTP 를 가짜로 바꿉니다.
실행: python -m pytest
"""

import smtplib

import pytest

from src import mailer


def fake_result(i):
    return {
        "id": f"t{i}", "source": "reddit_rss", "community": "r/gamedev", "author": "tester", "usefulness": 8,
        "permalink": f"https://www.reddit.com/r/gamedev/comments/t{i}/",
        "title_ko": f"테스트 글 {i} <특수문자>", "summary": ["첫 요약"], "tags": ["Unity"],
    }


def make_pdf(tmp_path):
    path = tmp_path / "reddit-digest-2026-09-29.pdf"
    path.write_bytes(b"%PDF-1.4 test")
    return path


def test_build_message(tmp_path):
    msg = mailer.build_message([fake_result(1), fake_result(2)], make_pdf(tmp_path), "2026-09-29",
                               "me@gmail.com", "to@gmail.com", "[다이제스트]")
    assert msg["Subject"] == "[다이제스트] 2026-09-29 - 2개 글"
    assert msg["To"] == "to@gmail.com"
    attachments = list(msg.iter_attachments())
    assert attachments[0].get_filename() == "reddit-digest-2026-09-29.pdf"
    text = msg.get_body(("plain",)).get_content()
    html = msg.get_body(("html",)).get_content()
    assert "https://www.reddit.com/r/gamedev/comments/t1/" in text
    assert "&lt;특수문자&gt;" in html  # HTML 특수문자가 이스케이프되어야 함


class FakeSMTP:
    sent = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, password):
        if password != "abcdabcdabcdabcd":
            raise smtplib.SMTPAuthenticationError(535, b"bad")

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def test_send_strips_spaces_in_app_password(monkeypatch, tmp_path):
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    msg = mailer.build_message([fake_result(1)], make_pdf(tmp_path), "d", "a", "b", "p")
    mailer.send(msg, "me@gmail.com", "abcd abcd abcd abcd")
    assert FakeSMTP.sent


def test_send_wrong_password_gives_clear_error(monkeypatch, tmp_path):
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    msg = mailer.build_message([fake_result(1)], make_pdf(tmp_path), "d", "a", "b", "p")
    with pytest.raises(RuntimeError, match="앱_비밀번호|GMAIL_APP_PASSWORD"):
        mailer.send(msg, "me@gmail.com", "wrong")
