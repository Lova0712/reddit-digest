"""
여러 출처(Reddit RSS, dev.to, Stack Exchange)에서 글을 모으는 모듈.

출처별 세부 동작은 src/sources/ 안의 파일에 있고, 여기서는
config.yaml 의 sources 설정대로 켜진 출처만 만들어서 차례로 불러 모은다.
테스트용 예시 글(samples/sample_posts.json)을 읽는 기능도 여기 있다.
"""

import json
import logging

from src.sources.devto import DevTo
from src.sources.reddit_rss import RedditRSS
from src.sources.stackexchange import StackExchange

log = logging.getLogger(__name__)

# config.yaml 의 sources 아래 이름 → 출처 클래스
SOURCE_CLASSES = {
    "reddit_rss": RedditRSS,
    "devto": DevTo,
    "stackexchange": StackExchange,
}


def make_sources(cfg):
    """켜져 있는(enabled: true) 출처만 만들어서 {이름: 출처} 로 돌려준다."""
    user_agent = cfg["http"]["user_agent"]
    return {
        name: SOURCE_CLASSES[name](scfg, user_agent)
        for name, scfg in cfg["sources"].items()
        if scfg.get("enabled")
    }


def fetch_all(sources):
    """모든 출처에서 글을 모은다. 한 출처가 실패해도 나머지는 계속."""
    posts = []
    for name, source in sources.items():
        try:
            got = source.fetch_posts()
            log.info("[%s] %d개 수집", name, len(got))
            posts += got
        except Exception as e:
            log.error("[%s] 수집 실패: %s", name, e)
    return posts


def fill_comments(posts, sources, limit):
    """댓글을 아직 안 가져온 글만 댓글을 채운다. 실패하면 댓글 없이 진행."""
    for p in posts:
        if p.get("comments") is not None:
            continue
        source = sources.get(p["source"])
        try:
            p["comments"] = source.fetch_comments(p, limit) if source else []
        except Exception as e:
            log.error("댓글 가져오기 실패 (%s): %s", p["id"], e)
            p["comments"] = []


def load_sample_posts(path):
    """테스트용 예시 글을 읽는다."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)["posts"]
