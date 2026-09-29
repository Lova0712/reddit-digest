"""
"쓸만한 글"을 고르는 모듈.

1) rule_filter  : 본문 길이·제외 키워드로 먼저 거른다 (무료, 빠름)
                  추천 수·댓글 수 기준은 출처마다 달라서 각 출처 모듈(src/sources/)이 미리 거름
2) rate_posts   : 통과한 글만 Claude(haiku)로 1~10점 유용도 평가
3) select_posts : 기준 점수 이상 중에서 하루 최대 개수만큼 고른다
"""

import logging
from datetime import datetime

from src import claude_cli

log = logging.getLogger(__name__)


def check_rules(post, cfg):
    """
    규칙 필터. 통과하면 None, 떨어지면 떨어진 이유(문자열)를 돌려준다.
    링크·이미지·영상만 있는 글은 본문이 비어 있어서 "본문이 너무 짧음"으로 빠진다.
    """
    title = post["title"].lower()
    for word in cfg["exclude_keywords"]:
        if word.lower() in title:
            return f"제외 키워드 ({word})"
    # Stack Exchange 처럼 답변이 이미 붙어 있는 글은 답변까지 합쳐서 잰다 (짧은 질문 + 좋은 답변도 가치가 있음)
    body_len = len(post.get("selftext", "").strip())
    body_len += sum(len(c["body"]) for c in (post.get("comments") or []) if post["source"] == "stackexchange")
    if body_len < cfg["min_body_length"]:
        return f"본문이 너무 짧음 ({body_len}자)"
    return None


def find_priority_keywords(post, cfg):
    """제목·태그·본문에 들어 있는 우선 키워드 목록 (평가 참고용)."""
    text = " ".join([post["title"], " ".join(post.get("tags", [])), post.get("selftext", "")]).lower()
    return [k for k in cfg["priority_keywords"] if k.lower() in text]


def interleave_by_source(posts):
    """
    출처별로 한 줄씩 번갈아 섞는다. (평가할 글 수를 제한할 때 한 출처만 몰리지 않게)
    예: [레딧1, 레딧2, 데브1, SE1] → [레딧1, 데브1, SE1, 레딧2]
    """
    groups = {}
    for p in posts:
        groups.setdefault(p["source"], []).append(p)
    mixed = []
    while any(groups.values()):
        for items in groups.values():
            if items:
                mixed.append(items.pop(0))
    return mixed


def rule_filter(posts, cfg):
    """
    규칙 필터를 통과한 글만 돌려준다.
    출처 안에서는 원래 순서(인기순)를 유지하되 우선 키워드가 많은 글을 앞으로, 출처끼리는 번갈아 섞는다.
    """
    passed = []
    for post in posts:
        reason = check_rules(post, cfg)
        if reason:
            log.info("제외: [%s] %s → %s", post["community"], post["title"][:60], reason)
            continue
        post["priority_hits"] = find_priority_keywords(post, cfg)
        passed.append(post)

    passed.sort(key=lambda p: len(p["priority_hits"]), reverse=True)  # 같은 개수끼리는 원래 순서 유지
    log.info("규칙 필터: %d개 중 %d개 통과", len(posts), len(passed))
    return interleave_by_source(passed)


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
- 오래된 글은 지금도 통하는 내용(원리, 설계, 경험)이면 괜찮지만,
  더 이상 쓰이지 않는 버전·도구에 묶인 내용이면 점수를 낮추세요.
reason 은 한국어 한 문장으로 쓰세요."""


def describe_counts(post):
    """추천·댓글 수를 글로 설명한다. Reddit RSS 는 수치 대신 이번 주 인기 순위를 알려 준다."""
    if post.get("score") is None:
        return f"이번 주 인기 순위 {post.get('rank', '?')}위 (추천 수 정보 없음)"
    return f"추천/반응 {post['score']} · 댓글/답변 {post.get('num_comments', 0)}"


def build_rating_prompt(post):
    """평가용 질문을 만든다. 한도 절약을 위해 본문·댓글은 앞부분만 보낸다."""
    comments = "\n".join(
        f"- {c['body'][:300]}" for c in (post.get("comments") or [])[:3]
    ) or "(댓글 정보 없음)"
    return f"""{RATING_GUIDE}

[출처] {post['community']}
[작성일] {datetime.fromtimestamp(post['created_utc']).strftime('%Y-%m-%d')}
[반응] {describe_counts(post)}
[태그] {', '.join(post.get('tags', [])) or '없음'}
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
    good.sort(key=lambda p: p["usefulness"], reverse=True)  # 같은 점수끼리는 원래 순서(출처 번갈아) 유지
    return good[:max_count]
