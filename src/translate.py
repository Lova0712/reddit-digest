"""
채택된 글을 한국어로 번역·요약하는 모듈 (Claude sonnet 사용).

결과 dict 모양
{
  "id", "source", "community"(출처 이름), "author", "created_date", "permalink",
  "score", "num_comments" (모르면 None), "usefulness",
  "original_title",
  "title_ko"   : 한국어 제목,
  "summary"    : 핵심 요약 3~5줄 (리스트),
  "body_ko"    : 본문 번역 (길면 핵심 위주 요약 번역),
  "comments"   : [{"author", "summary"}] 유용한 댓글 1~3개,
  "tags"       : 분류 태그 (Notion multi_select 용)
}
"""

import logging
from datetime import datetime

from src import claude_cli

log = logging.getLogger(__name__)

# Notion 태그로 쓸 분류 목록 (이 중에서만 고르게 함)
TAG_OPTIONS = [
    "튜토리얼", "포스트모템", "마케팅", "출시", "기술 Q&A", "Unity",
    "프로그래밍", "게임 디자인", "아트", "사운드", "비즈니스", "커리어", "도구",
]

TRANSLATE_SYSTEM_PROMPT = (
    "당신은 게임 개발 전문 번역가입니다. 영어 게임개발 커뮤니티 글(Reddit, dev.to, Stack Exchange)을 입문 인디 게임 개발자가 "
    "읽기 쉬운 자연스러운 한국어로 번역하고 요약합니다."
)

TRANSLATE_SCHEMA = {
    "type": "object",
    "properties": {
        "title_ko": {"type": "string", "description": "한국어 제목"},
        "summary": {
            "type": "array",
            "items": {"type": "string"},
            "description": "핵심 요약 3~5줄",
        },
        "body_ko": {"type": "string", "description": "본문 한국어 번역 (문단은 빈 줄로 구분)"},
        "comments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "author": {"type": "string"},
                    "summary": {"type": "string", "description": "댓글 내용 한국어 요약 1~3문장"},
                },
                "required": ["author", "summary"],
            },
            "description": "유용한 댓글 1~3개",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string", "enum": TAG_OPTIONS},
            "description": "글에 맞는 분류 1~3개",
        },
    },
    "required": ["title_ko", "summary", "body_ko", "comments", "tags"],
}

TRANSLATE_RULES = """번역 규칙:
1. title_ko: 원문 제목을 자연스러운 한국어로.
2. summary: 이 글에서 입문 개발자가 가져갈 핵심을 3~5개의 짧은 문장으로.
3. body_ko: 본문을 한국어로 번역. 본문이 길면 핵심 부분 위주로 요약 번역하고,
   생략한 부분은 "(중략)"으로 표시. 코드는 번역하지 말고 그대로 둘 것.
4. comments: 아래 댓글(또는 답변) 중 유용한 것 1~3개를 골라 작성자와 함께 한국어로 요약.
   [채택된 답변] 표시가 있으면 요약 앞에 "(채택)"을 붙일 것. 쓸만한 댓글이 없으면 빈 목록.
5. tags: 지정된 분류 중 1~3개.
6. 게임 개발 용어는 처음 나올 때 괄호로 원어를 함께 적을 것. 예: 오브젝트 풀링(Object Pooling)
7. 원문에 없는 내용을 지어내지 말 것."""


def build_translate_prompt(post, max_body_chars):
    body = post["selftext"]
    if len(body) > max_body_chars:
        body = body[:max_body_chars] + "\n\n[... 원문이 길어서 이후 생략됨 ...]"
    comments = "\n\n".join(
        f"[댓글 작성자: {c['author']}]\n{c['body'][:1500]}"
        for c in (post.get("comments") or [])
    ) or "(댓글 없음)"
    return f"""{TRANSLATE_RULES}

[출처] {post['community']}
[원문 제목] {post['title']}

[원문 본문]
{body}

[추천 많은 댓글]
{comments}
"""


def translate_post(post, translate_cfg, ask=claude_cli.ask_json):
    """글 하나를 번역·요약해서 결과 dict 를 돌려준다. 실패하면 예외를 그대로 올린다."""
    result = ask(
        build_translate_prompt(post, translate_cfg["max_body_chars"]),
        TRANSLATE_SCHEMA,
        TRANSLATE_SYSTEM_PROMPT,
        model=translate_cfg["model"],
        timeout=translate_cfg["timeout_seconds"],
        command=translate_cfg["claude_command"],
    )

    return {
        # 원문 정보 (출처 표기용 - 항상 함께 보관)
        "id": post["id"],
        "source": post["source"],
        "community": post["community"],
        "author": post["author"],
        "created_date": datetime.fromtimestamp(post["created_utc"]).strftime("%Y-%m-%d"),
        "permalink": post["permalink"],
        "score": post.get("score"),
        "num_comments": post.get("num_comments"),
        "usefulness": post.get("usefulness"),
        "original_title": post["title"],
        # 번역 결과
        "title_ko": result["title_ko"],
        "summary": result["summary"][:5],
        "body_ko": result["body_ko"],
        "comments": result["comments"][:3],
        "tags": [t for t in result["tags"] if t in TAG_OPTIONS][:3],
    }
