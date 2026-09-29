"""
출처(Reddit RSS, dev.to, Stack Exchange) 테스트.
실제 인터넷 요청 대신 미리 적어 둔 응답을 돌려주는 가짜 함수를 사용합니다.
실행: python -m pytest
"""

from src import http_util
from src.sources import devto, reddit_rss, stackexchange
from src.text_util import byline, html_to_text

UA = "test-agent"

# ───────────── HTML → 텍스트 ─────────────

def test_html_to_text():
    html = ("<p>Hello &amp; <b>world</b></p><ul><li>one</li><li>two</li></ul>"
            "<pre><code>int a = 1;\n  int b;</code></pre><p><a href='https://x.com'>link</a></p>")
    text = html_to_text(html)
    assert "Hello & world" in text
    assert "- one" in text and "- two" in text
    assert "```\nint a = 1;\n  int b;\n```" in text  # 코드 들여쓰기 유지
    assert "link (https://x.com)" in text


def test_byline_without_score():
    r = {"community": "r/gamedev", "author": "a", "created_date": "2026-09-29", "score": None}
    assert byline(r) == "r/gamedev · a · 작성일 2026-09-29"
    r.update(score=10, num_comments=3)
    assert byline(r).endswith("추천 10 · 댓글 3")


# ───────────── Reddit RSS ─────────────

LISTING = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <entry>
  <author><name>/u/alice</name></author>
  <content type="html">&lt;!-- SC_OFF --&gt;&lt;div class="md"&gt;&lt;p&gt;My long post body&lt;/p&gt;&lt;/div&gt;&lt;!-- SC_ON --&gt; &amp;#32; submitted by &lt;a href="x"&gt;/u/alice&lt;/a&gt;</content>
  <id>t3_abc123</id>
  <link href="https://www.reddit.com/r/gamedev/comments/abc123/my_post/" />
  <published>2026-09-23T12:58:48+00:00</published>
  <title>Tips &amp;amp; tricks</title>
 </entry>
 <entry>
  <author><name>/u/bob</name></author>
  <content type="html">&lt;table&gt;&lt;img src="x.png"/&gt;&lt;/table&gt; submitted by bob</content>
  <id>t3_img999</id>
  <link href="https://www.reddit.com/r/gamedev/comments/img999/pic/" />
  <published>2026-09-24T00:00:00+00:00</published>
  <title>Look at my art</title>
 </entry>
</feed>"""

COMMENTS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <entry><author><name>/u/alice</name></author><content type="html">post itself</content><id>t3_abc123</id></entry>
 <entry><author><name>/u/AutoModerator</name></author><content type="html">bot</content><id>t1_bot</id></entry>
 <entry><author><name>/u/carol</name></author><content type="html">&lt;p&gt;Great advice&lt;/p&gt;</content><id>t1_c1</id></entry>
</feed>"""


def test_reddit_parse_listing():
    posts = reddit_rss.parse_listing(LISTING, "gamedev")
    assert posts[0]["id"] == "reddit:abc123"
    assert posts[0]["author"] == "alice"
    assert posts[0]["title"] == "Tips & tricks"
    assert posts[0]["selftext"] == "My long post body"  # "submitted by" 안내는 빠져야 함
    assert posts[0]["score"] is None and posts[0]["rank"] == 1
    assert posts[1]["selftext"] == ""  # 이미지 글은 본문 없음


def test_reddit_parse_comments_skips_post_and_bots():
    comments = reddit_rss.parse_comments(COMMENTS, limit=5)
    assert [c["author"] for c in comments] == ["carol"]
    assert comments[0]["body"] == "Great advice"


class FakeResp:
    def __init__(self, text="", data=None, headers=None):
        self.text, self._data, self.headers = text, data, headers or {}

    def json(self):
        return self._data


def test_reddit_waits_when_rate_limit_used_up(monkeypatch):
    """남은 요청 횟수가 0이면 reset 시간만큼 기다렸다가 다음 요청을 보낸다."""
    monkeypatch.setattr(http_util, "get", lambda *a, **k: FakeResp(LISTING, headers={
        "x-ratelimit-remaining": "0.0", "x-ratelimit-reset": "48"}))
    slept = []
    monkeypatch.setattr(reddit_rss.time, "sleep", lambda s: slept.append(s))
    src = reddit_rss.RedditRSS({"subreddits": ["gamedev", "Unity3D"], "top_time_filter": "week",
                                "max_posts_per_subreddit": 5, "request_delay_seconds": 10}, UA)
    posts = src.fetch_posts()
    assert len(posts) == 4
    assert len(slept) == 1 and slept[0] >= 48  # 두 번째 요청 전에 약 50초 대기


# ───────────── dev.to ─────────────

ARTICLE = {"id": 11, "title": "Unity tips", "url": "https://dev.to/u/unity-tips",
           "public_reactions_count": 20, "comments_count": 3, "published_at": "2026-09-20T10:00:00Z",
           "user": {"username": "devuser"}, "tag_list": ["gamedev", "unity3d"]}
LOW = dict(ARTICLE, id=12, public_reactions_count=1)


def test_devto_filters_by_reactions_and_dedups(monkeypatch):
    calls = []

    def fake_get(url, ua, params=None, **k):
        calls.append(url)
        if url.endswith("/articles"):
            return FakeResp(data=[ARTICLE, LOW])  # 두 태그 모두 같은 글이 나옴
        return FakeResp(data={"body_markdown": "---\ntitle: x\n---\nReal body"})

    monkeypatch.setattr(http_util, "get", fake_get)
    monkeypatch.setattr(devto.time, "sleep", lambda s: None)
    src = devto.DevTo({"tags": ["gamedev", "unity3d"], "top_days": 7, "max_posts_per_tag": 30,
                       "min_reactions": 5, "min_comments": 0, "request_delay_seconds": 0}, UA)
    posts = src.fetch_posts()
    assert [p["id"] for p in posts] == ["devto:11"]  # 반응 적은 글 제외, 중복 제거
    assert posts[0]["selftext"] == "Real body"      # 앞부분 설정(front matter) 제거
    assert posts[0]["community"] == "dev.to #gamedev"
    assert sum(1 for u in calls if "/articles/11" in u) == 1  # 본문은 한 번만 요청


# ───────────── Stack Exchange ─────────────

def test_stackexchange_questions_with_answers(monkeypatch):
    questions = {"items": [
        {"question_id": 1, "title": "How to &quot;pool&quot;?", "score": 5, "answer_count": 2, "link": "https://gamedev.stackexchange.com/q/1",
         "creation_date": 1790000000, "owner": {"display_name": "asker"}, "body": "<p>Question body</p>", "tags": ["unity"]},
        {"question_id": 2, "title": "Low", "score": 0, "answer_count": 1, "link": "l", "creation_date": 1, "body": ""},
    ]}
    answers = {"items": [
        {"question_id": 1, "score": 3, "is_accepted": False, "owner": {"display_name": "b"}, "body": "<p>Other</p>"},
        {"question_id": 1, "score": 1, "is_accepted": True, "owner": {"display_name": "a"}, "body": "<p>Accepted</p>"},
    ]}

    def fake_get(url, ua, params=None, **k):
        return FakeResp(data=answers if "/answers" in url else questions)

    monkeypatch.setattr(http_util, "get", fake_get)
    src = stackexchange.StackExchange({"site": "gamedev", "days": 14, "max_questions": 30, "min_score": 2,
                                       "min_answers": 1, "answers_per_question": 3}, UA)
    posts = src.fetch_posts()
    assert [p["id"] for p in posts] == ["se:1"]
    p = posts[0]
    assert p["title"] == 'How to "pool"?'
    assert p["comments"][0]["body"].startswith("[채택된 답변]")  # 채택 답변이 맨 앞
    assert src.fetch_comments(p, 1) == p["comments"][:1]
