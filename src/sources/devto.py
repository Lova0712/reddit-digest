"""
dev.to 공식 API 로 게임개발 태그의 인기 글을 가져온다. (가입·키 없이 사용 가능)

- 목록: /api/articles?tag=<태그>&top=<일수>  → 최근 N일 인기 글
- 본문: /api/articles/<id>                    → body_markdown (목록에는 본문이 없음)
- 댓글: /api/comments?a_id=<id>
반응 수(public_reactions_count)와 댓글 수로 먼저 걸러서, 통과한 글만 본문을 받는다 (요청 절약).
"""

import logging
import re
import time
from datetime import datetime

from src import http_util
from src.text_util import clean_title, html_to_text

log = logging.getLogger(__name__)

API = "https://dev.to/api"


def strip_front_matter(markdown):
    """본문 맨 앞의 '---\\ntitle: ...\\n---' 설정 부분을 뺀다."""
    return re.sub(r"\A---\n.*?\n---\n", "", markdown or "", flags=re.S).strip()


def to_post(article, tag, body_markdown):
    return {
        "id": f"devto:{article['id']}",
        "source": "devto",
        "community": f"dev.to #{tag}",
        "title": clean_title(article["title"]),
        "author": article["user"]["username"],
        "created_utc": datetime.fromisoformat(article["published_at"].replace("Z", "+00:00")).timestamp(),
        "permalink": article["url"],
        "selftext": strip_front_matter(body_markdown),
        "score": article.get("public_reactions_count", 0),
        "num_comments": article.get("comments_count", 0),
        "tags": article.get("tag_list") or [],
        "comments": None,
    }


class DevTo:
    def __init__(self, cfg, user_agent):
        self.cfg = cfg
        self.user_agent = user_agent

    def _get_json(self, path, params=None):
        resp = http_util.get(f"{API}/{path}", self.user_agent, params=params)
        time.sleep(self.cfg["request_delay_seconds"])
        return resp.json()

    def fetch_posts(self):
        cfg = self.cfg
        chosen = {}  # id → (글 정보, 태그)  여러 태그에 같은 글이 있으면 한 번만
        for tag in cfg["tags"]:
            try:
                articles = self._get_json("articles", {"tag": tag, "top": cfg["top_days"],
                                                       "per_page": cfg["max_posts_per_tag"]})
            except Exception as e:
                log.error("dev.to #%s 목록을 가져오지 못했습니다: %s", tag, e)
                continue
            passed = [a for a in articles
                      if a.get("public_reactions_count", 0) >= cfg["min_reactions"]
                      and a.get("comments_count", 0) >= cfg["min_comments"]]
            log.info("dev.to #%s: %d개 중 반응 기준 통과 %d개", tag, len(articles), len(passed))
            for a in passed:
                chosen.setdefault(a["id"], (a, tag))

        posts = []
        for a, tag in chosen.values():
            try:
                detail = self._get_json(f"articles/{a['id']}")
                posts.append(to_post(a, tag, detail.get("body_markdown", "")))
            except Exception as e:
                log.error("dev.to 글 본문을 가져오지 못했습니다 (%s): %s", a["id"], e)
        # 반응 많은 순으로
        posts.sort(key=lambda p: p["score"], reverse=True)
        return posts

    def fetch_comments(self, post, limit):
        article_id = post["id"].removeprefix("devto:")
        data = self._get_json("comments", {"a_id": article_id})
        comments = []
        for c in data:  # 최상위 댓글만 (답글 제외)
            body = html_to_text(c.get("body_html", ""))
            if body:
                comments.append({"author": c["user"]["username"], "score": None, "body": body})
            if len(comments) >= limit:
                break
        return comments
