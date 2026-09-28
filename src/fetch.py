"""
Reddit 글을 가져오는 모듈 (공식 API, praw 사용).

Reddit API 승인 전에는 samples/sample_posts.json 의 예시 글을 대신 읽습니다.
어느 쪽이든 글 1개는 아래 모양의 dict 로 통일합니다.

{
  "id", "subreddit", "title", "author", "created_utc", "score", "num_comments",
  "permalink"(원문 주소), "url"(링크 글의 대상 주소), "selftext"(본문),
  "flair", "is_self", "post_hint", "over_18", "stickied",
  "comments": [{"author", "score", "body"}, ...]
}
"""

import json
import logging
import os
import time

log = logging.getLogger(__name__)


def has_reddit_keys():
    """.env 에 Reddit 키가 채워져 있으면 True."""
    return bool(os.getenv("REDDIT_CLIENT_ID") and os.getenv("REDDIT_CLIENT_SECRET"))


def load_sample_posts(path):
    """Reddit 승인 전 테스트용 예시 글을 읽는다."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["posts"]


def make_reddit():
    """.env 의 키로 읽기 전용 Reddit 클라이언트를 만든다."""
    import praw  # Reddit 키가 있을 때만 필요하므로 여기서 불러옴

    reddit = praw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        user_agent=os.getenv("REDDIT_USER_AGENT"),
    )
    reddit.read_only = True
    return reddit


def with_retry(func, max_retries=3, base_delay=2):
    """
    func() 를 실행하고, 서버 에러·요청 제한이면 기다렸다가 다시 시도한다.
    기다리는 시간은 2초 → 4초 → 8초 ... 로 두 배씩 늘어난다 (지수 백오프).
    """
    import prawcore

    retry_errors = (
        prawcore.exceptions.ServerError,       # Reddit 서버 문제 (5xx)
        prawcore.exceptions.RequestException,  # 네트워크 문제
        prawcore.exceptions.TooManyRequests,   # 요청 제한 (429)
    )
    for attempt in range(max_retries + 1):
        try:
            return func()
        except retry_errors as e:
            if attempt == max_retries:
                raise
            wait = base_delay * (2 ** attempt)
            log.warning("Reddit 요청 실패(%s), %d초 후 다시 시도합니다.", type(e).__name__, wait)
            time.sleep(wait)


def submission_to_dict(s):
    """praw 의 글(Submission) 객체를 우리 형식의 dict 로 바꾼다."""
    # vars(s) 에서 꺼내면 없는 값을 읽으려고 추가 요청을 보내는 일을 막을 수 있습니다.
    raw = vars(s)
    return {
        "id": s.id,
        "subreddit": s.subreddit.display_name,
        "title": s.title,
        "author": s.author.name if s.author else "[deleted]",
        "created_utc": s.created_utc,
        "score": s.score,
        "num_comments": s.num_comments,
        "permalink": "https://www.reddit.com" + s.permalink,
        "url": s.url,
        "selftext": s.selftext or "",
        "flair": raw.get("link_flair_text") or "",
        "is_self": s.is_self,
        "post_hint": raw.get("post_hint", ""),
        "over_18": raw.get("over_18", False),
        "stickied": raw.get("stickied", False),
        "comments": [],
    }


def fetch_listings(reddit, cfg):
    """
    각 서브레딧의 top(기간: cfg 설정) 과 hot 글을 가져온다.
    top 과 hot 에 같은 글이 있으면 한 번만 남긴다.
    """
    posts = {}
    limit = cfg["max_posts_per_subreddit"]
    delay = cfg["request_delay_seconds"]
    retries = cfg["max_retries"]

    for name in cfg["subreddits"]:
        sub = reddit.subreddit(name)
        listings = [
            ("top", lambda: list(sub.top(time_filter=cfg["top_time_filter"], limit=limit))),
            ("hot", lambda: list(sub.hot(limit=limit))),
        ]
        for kind, get_list in listings:
            try:
                items = with_retry(get_list, retries, delay)
            except Exception as e:
                # 한 서브레딧이 실패해도 나머지는 계속 진행
                log.error("r/%s %s 목록을 가져오지 못했습니다: %s", name, kind, e)
                continue
            for s in items:
                posts[s.id] = submission_to_dict(s)
            log.info("r/%s %s: %d개", name, kind, len(items))
            time.sleep(delay)  # Reddit 요청 제한을 지키기 위한 대기

    return list(posts.values())


def fetch_comments(reddit, post, limit, cfg):
    """글 하나의 추천 많은 댓글을 limit 개까지 가져온다."""

    def get():
        s = reddit.submission(id=post["id"])
        s.comment_sort = "top"
        s.comments.replace_more(limit=0)  # "댓글 더 보기"는 펼치지 않음 (요청 절약)
        result = []
        for c in s.comments:
            if c.stickied or c.author is None:  # 고정 댓글(보통 봇), 삭제된 댓글 제외
                continue
            result.append({"author": c.author.name, "score": c.score, "body": c.body})
            if len(result) >= limit:
                break
        return result

    comments = with_retry(get, cfg["max_retries"], cfg["request_delay_seconds"])
    time.sleep(cfg["request_delay_seconds"])
    return comments
