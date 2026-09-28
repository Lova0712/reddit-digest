"""
"쓸만한 글"을 고르는 모듈.

1) rule_filter  : 점수·댓글 수·본문 길이·제외 키워드로 먼저 거른다 (무료, 빠름)
2) rate_posts   : 통과한 글만 Claude(haiku)로 1~10점 유용도 평가
3) select_posts : 기준 점수 이상 중에서 하루 최대 개수만큼 고른다
"""

import logging

from src import claude_cli

log = logging.getLogger(__name__)

# 이미지·영상만 있는 글을 알아보는 표시
MEDIA_HINTS = ("image", "hosted:video", "rich:video")


def check_rules(post, cfg):
    """
    규칙 필터. 통과하면 None, 떨어지면 떨어진 이유(문자열)를 돌려준다.
    """
    title = post["title"].lower()
    flair = post.get("flair", "").lower()

    if post.get("stickied"):
        return "고정 글(공지)"
    if post.get("over_18"):
        return "성인 글"
    if post["score"] < cfg["min_score"]:
        return f"추천 수 부족 ({post['score']} < {cfg['min_score']})"
    if post["num_comments"] < cfg["min_comments"]:
        return f"댓글 수 부족 ({post['num_comments']} < {cfg['min_comments']})"
    if flair and flair in [f.lower() for f in cfg["exclude_flairs"]]:
        return f"제외 플레어 ({post['flair']})"
    for word in cfg["exclude_keywords"]:
        if word.lower() in title:
            return f"제외 키워드 ({word})"
    if post.get("post_hint") in MEDIA_HINTS:
        return "이미지/영상만 있는 글"
    if len(post.get("selftext", "").strip()) < cfg["min_body_length"]:
        return f"본문이 너무 짧음 ({len(post.get('selftext', '').strip())}자)"
    return None


def find_priority_keywords(post, cfg):
    """제목·플레어·본문에 들어 있는 우선 키워드 목록 (평가 참고용)."""
    text = " ".join([post["title"], post.get("flair", ""), post.get("selftext", "")]).lower()
    return [k for k in cfg["priority_keywords"] if k.lower() in text]


def rule_filter(posts, cfg):
    """규칙 필터를 통과한 글만 돌려준다. 우선 키워드가 많고 점수가 높은 순으로 정렬."""
    passed = []
    for post in posts:
        reason = check_rules(post, cfg)
        if reason:
            log.info("제외: [%s] %s → %s", post["subreddit"], post["title"][:60], reason)
            continue
        post["priority_hits"] = find_priority_keywords(post, cfg)
        passed.append(post)

    passed.sort(key=lambda p: (len(p["priority_hits"]), p["score"]), reverse=True)
    log.info("규칙 필터: %d개 중 %d개 통과", len(posts), len(passed))
    return passed


# ───────────── Claude 유용도 평가 ─────────────

RATING_SYSTEM_PROMPT = (
    "당신은 게임 개발을 막 시작한 인디 개발자를 위해 Reddit 글을 고르는 편집자입니다. "
    "주어진 글이 그런 입문 인디 개발자에게 얼마나 유용한지 1~10점으로 평가합니다."
)

RATING_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "description": "유용도 1~10점"},
        "reason": {"type": "string", "description": "점수 이유, 한국어 한 문장"},
    },
    "required": ["score", "reason"],
}

RATING_GUIDE = """평가 기준:
- 높은 점수(8~10): 따라 할 수 있는 튜토리얼, 구체적인 수치나 교훈이 있는 포스트모템,
  마케팅/출시 경험담, 좋은 답변이 달린 기술 Q&A, 바로 써먹을 수 있는 Unity 팁
- 중간 점수(5~7): 참고할 만한 토론이지만 구체성이 부족한 글
- 낮은 점수(1~4): 밈/농담, 자기 홍보, 결과물 자랑, 내용 없는 짧은 질문, 불평이나 잡담
reason 은 한국어 한 문장으로 쓰세요."""


def build_rating_prompt(post):
    """평가용 질문을 만든다. 한도 절약을 위해 본문·댓글은 앞부분만 보낸다."""
    comments = "\n".join(
        f"- ({c['score']}점) {c['body'][:300]}" for c in post.get("comments", [])[:3]
    ) or "(댓글 정보 없음)"
    return f"""{RATING_GUIDE}

[서브레딧] r/{post['subreddit']}
[플레어] {post.get('flair') or '없음'}
[추천 수] {post['score']} / [댓글 수] {post['num_comments']}
[우선 키워드] {', '.join(post.get('priority_hits', [])) or '없음'}
[제목] {post['title']}
[본문 앞부분]
{post['selftext'][:2000]}

[추천 많은 댓글]
{comments}
"""


def rate_posts(posts, translate_cfg, ask=claude_cli.ask_json):
    """
    글마다 Claude 로 유용도를 평가해서 post["usefulness"], post["rating_reason"] 을 채운다.
    평가에 실패한 글은 이번 실행에서 빼고, 다음 실행 때 다시 평가된다.
    ask 인자는 테스트에서 가짜 함수로 바꿔 끼우기 위한 것.
    """
    rated = []
    for post in posts:
        try:
            result = ask(
                build_rating_prompt(post),
                RATING_SCHEMA,
                RATING_SYSTEM_PROMPT,
                model=translate_cfg["rating_model"],
                timeout=translate_cfg["timeout_seconds"],
                command=translate_cfg["claude_command"],
            )
            post["usefulness"] = max(1, min(10, int(result["score"])))  # 1~10 범위로 고정
            post["rating_reason"] = result["reason"]
            rated.append(post)
            log.info("평가 %2d점: %s", post["usefulness"], post["title"][:60])
        except Exception as e:
            # 한 글의 실패가 전체를 멈추지 않게 함
            log.error("평가 실패 (%s): %s", post["id"], e)
    return rated


def select_posts(rated, min_score, max_count):
    """기준 점수 이상인 글을 유용도 → 추천 수 순으로 정렬해 max_count 개까지 고른다."""
    good = [p for p in rated if p["usefulness"] >= min_score]
    good.sort(key=lambda p: (p["usefulness"], p["score"]), reverse=True)
    return good[:max_count]
