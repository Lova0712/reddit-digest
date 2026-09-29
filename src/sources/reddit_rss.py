"""
Reddit 공개 RSS 피드로 글과 댓글을 가져온다. (Reddit API 는 승인이 거절되어 쓰지 않음)

- 목록: https://www.reddit.com/r/<서브레딧>/top/.rss?t=week  → 이번 주 인기순
- 댓글: <글 주소>/.rss?sort=top                               → 추천 많은 순
- RSS 에는 추천 수·댓글 수가 없어서 score/num_comments 는 None.
  대신 top 목록의 순서(rank)가 인기순이라 그 순서를 그대로 쓴다.

요청 제한이 매우 엄격하다 (로그인 없이 대략 1분에 1번).
응답 헤더(x-ratelimit-remaining / reset)를 읽어서 다음 요청까지 필요한 만큼 기다린다.
"""

import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime

from src import http_util
from src.text_util import clean_title, html_to_text

log = logging.getLogger(__name__)

ATOM = "{http://www.w3.org/2005/Atom}"
BASE = "https://www.reddit.com"
SKIP_AUTHORS = {"AutoModerator"}


def extract_body(content_html):
    """
    RSS 본문 HTML 에서 글 내용만 꺼낸다.
    텍스트 글은 <!-- SC_OFF --> ... <!-- SC_ON --> 사이에 본문이 있고, 그 뒤는 "submitted by ..." 안내.
    링크·이미지 글은 SC_OFF 가 없으므로 본문 없음("")으로 본다.
    """
    if not content_html or "<!-- SC_OFF -->" not in content_html:
        return ""
    inner = content_html.split("<!-- SC_OFF -->", 1)[1].split("<!-- SC_ON -->", 1)[0]
    return html_to_text(inner)


def parse_time(text):
    """'2026-09-23T12:58:48+00:00' → 초 단위 시각."""
    return datetime.fromisoformat(text).timestamp()


def author_name(entry):
    name = entry.findtext(f"{ATOM}author/{ATOM}name") or "[deleted]"
    return name.removeprefix("/u/")


def parse_listing(xml_text, subreddit):
    """서브레딧 top RSS 를 글 목록으로 바꾼다."""
    root = ET.fromstring(xml_text)
    posts = []
    for rank, e in enumerate(root.findall(f"{ATOM}entry"), 1):
        raw_id = e.findtext(f"{ATOM}id") or ""          # 예: t3_1wo5asm
        link = e.find(f"{ATOM}link")
        posts.append({
            "id": "reddit:" + raw_id.removeprefix("t3_"),
            "source": "reddit_rss",
            "community": f"r/{subreddit}",
            "title": clean_title(e.findtext(f"{ATOM}title")),
            "author": author_name(e),
            "created_utc": parse_time(e.findtext(f"{ATOM}published")),
            "permalink": link.get("href") if link is not None else "",
            "selftext": extract_body(e.findtext(f"{ATOM}content")),
            "score": None,
            "num_comments": None,
            "rank": rank,  # top 목록에서의 순위 (1 = 가장 인기)
            "tags": [],
            "comments": None,
        })
    return posts


def parse_comments(xml_text, limit):
    """댓글 RSS 를 댓글 목록으로 바꾼다. 첫 항목(t3_)은 글 자신이라 건너뛴다."""
    root = ET.fromstring(xml_text)
    comments = []
    for e in root.findall(f"{ATOM}entry"):
        if (e.findtext(f"{ATOM}id") or "").startswith("t3_"):
            continue
        author = author_name(e)
        if author in SKIP_AUTHORS:
            continue
        body = html_to_text(e.findtext(f"{ATOM}content"))
        if body:
            comments.append({"author": author, "score": None, "body": body})
        if len(comments) >= limit:
            break
    return comments


class RedditRSS:
    def __init__(self, cfg, user_agent):
        self.cfg = cfg
        self.user_agent = user_agent
        self.next_allowed = 0.0  # 다음 요청을 보내도 되는 시각

    def _get(self, url, params):
        """Reddit 요청 제한을 지키면서 GET."""
        wait = self.next_allowed - time.time()
        if wait > 0:
            log.info("Reddit 요청 제한 때문에 %d초 기다립니다.", int(wait) + 1)
            time.sleep(wait)
        resp = http_util.get(url, self.user_agent, params=params, base_delay=30)

        gap = self.cfg["request_delay_seconds"]
        try:
            remaining = float(resp.headers.get("x-ratelimit-remaining", "1"))
            reset = float(resp.headers.get("x-ratelimit-reset", "0"))
            if remaining < 1:
                gap = max(gap, reset + 2)  # 남은 횟수가 없으면 초기화될 때까지 대기
        except ValueError:
            pass
        self.next_allowed = time.time() + gap
        return resp

    def fetch_posts(self):
        posts = []
        for sub in self.cfg["subreddits"]:
            try:
                resp = self._get(f"{BASE}/r/{sub}/top/.rss",
                                 {"t": self.cfg["top_time_filter"], "limit": self.cfg["max_posts_per_subreddit"]})
                got = parse_listing(resp.text, sub)
                log.info("r/%s top: %d개", sub, len(got))
                posts += got
            except Exception as e:
                # 한 서브레딧이 실패해도 나머지는 계속
                log.error("r/%s 목록을 가져오지 못했습니다: %s", sub, e)
        return posts

    def fetch_comments(self, post, limit):
        resp = self._get(post["permalink"].rstrip("/") + "/.rss", {"sort": "top", "limit": limit + 5})
        return parse_comments(resp.text, limit)
