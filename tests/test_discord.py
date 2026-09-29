"""
디스코드 웹훅 테스트. 실제로 보내지 않도록 requests.post 를 가짜로 바꿉니다.
실행: python -m pytest
"""

import json

import requests

from src import discord_post


def fake_result(i, summary_len=100):
    return {
        "id": f"t{i}", "source": "devto", "community": "dev.to #gamedev", "author": "tester",
        "created_date": "2026-09-29", "permalink": f"https://dev.to/t/{i}", "score": 10, "num_comments": 2,
        "usefulness": 8, "original_title": "Original", "title_ko": f"테스트 글 {i}",
        "summary": ["가" * summary_len] * 5, "comments": [{"author": "c1", "summary": "좋은 댓글"}],
        "tags": ["Unity"], "notion_url": "https://notion.so/page",
    }


class FakeResp:
    def __init__(self, status=204, data=None):
        self.status_code, self._data, self.text = status, data or {}, ""

    def json(self):
        return self._data


def test_build_embed():
    e = discord_post.build_embed(1, fake_result(1))
    assert e["title"] == "1. 테스트 글 1"
    assert e["url"] == "https://dev.to/t/1"
    assert "Notion에서 전체 번역 보기" in e["description"]
    assert e["color"] == discord_post.SOURCE_COLORS["devto"]


def test_embed_limits_are_respected():
    """아주 긴 요약이 와도 디스코드 제한을 넘지 않는다."""
    e = discord_post.build_embed(1, fake_result(1, summary_len=5000))
    assert len(e["description"]) <= 4096
    assert len(e["title"]) <= 256


def test_group_embeds_by_count_and_size():
    embeds = [discord_post.build_embed(i, fake_result(i, summary_len=200)) for i in range(1, 13)]
    groups = discord_post.group_embeds(embeds)
    assert sum(len(g) for g in groups) == 12
    for g in groups:
        assert len(g) <= 10
        assert sum(discord_post.embed_size(e) for e in g) <= discord_post.MAX_CHARS_PER_MESSAGE


def test_send_digest_posts_header_with_pdf_then_cards(monkeypatch, tmp_path):
    sent = []

    def fake_post(url, json=None, data=None, files=None, timeout=None):
        sent.append({"json": json, "data": data, "files": files})
        return FakeResp()

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(discord_post.time, "sleep", lambda s: None)
    pdf = tmp_path / "reddit-digest-2026-09-29.pdf"
    pdf.write_bytes(b"%PDF test")

    discord_post.send_digest("https://discord.test/webhook", [fake_result(1), fake_result(2)], pdf, "2026-09-29")
    header = json.loads(sent[0]["data"]["payload_json"])
    assert "오늘의 글 2개" in header["content"]
    assert sent[0]["files"]["files[0]"][0] == "reddit-digest-2026-09-29.pdf"
    assert len(sent[1]["json"]["embeds"]) == 2
    assert sent[1]["json"]["allowed_mentions"] == {"parse": []}  # @everyone 알림 방지


def test_retry_after_rate_limit(monkeypatch):
    responses = [FakeResp(429, {"retry_after": 1.5}), FakeResp(204)]
    waits = []
    monkeypatch.setattr(requests, "post", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr(discord_post.time, "sleep", lambda s: waits.append(s))
    discord_post.post("https://discord.test/webhook", {"content": "hi"})
    assert waits[0] >= 1.5
    assert not responses  # 두 번 보냄
