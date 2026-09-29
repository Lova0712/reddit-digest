"""
디스코드 채널에 다이제스트를 올리는 모듈 (웹훅 사용 - 봇 계정·서버 필요 없음).

올리는 모양
  1) 첫 메시지: "📚 게임개발 커뮤니티 다이제스트 날짜 · 글 N개" + PDF 첨부
  2) 이어서 글마다 카드(embed) 한 장: 제목(원문 링크), 출처·유용도·태그, 핵심 요약, 댓글 요약,
     Notion 전체 번역 링크

디스코드 제한 (넘으면 요청이 거절되므로 코드에서 맞춤)
  - 메시지 하나에 카드 최대 10장, 카드 글자 합계 최대 6000자
  - 카드 제목 256자, 설명 4096자, 칸(field) 값 1024자, 아래쪽 글(footer) 2048자
  - 첨부 파일 최대 10MB
  - 너무 빨리 보내면 429 응답 → 알려 준 시간(retry_after)만큼 기다렸다 다시 보냄

개인 서버에 올리는 용도입니다. (원문 저작권은 작성자에게 있으므로 공개 서버에 재배포하지 않기)
"""

import json
import logging
import time
from pathlib import Path

import requests

from src.pdf_maker import TITLE
from src.text_util import byline

log = logging.getLogger(__name__)

MAX_EMBEDS_PER_MESSAGE = 10
MAX_CHARS_PER_MESSAGE = 5500  # 제한은 6000자지만 여유를 둠
MAX_FILE_BYTES = 10 * 1024 * 1024

# 출처별 카드 왼쪽 색깔
SOURCE_COLORS = {
    "reddit_rss": 0xFF4500,     # Reddit 주황
    "devto": 0x3B49DF,          # dev.to 파랑
    "stackexchange": 0xF48024,  # Stack Exchange 주황-노랑
}


def cut(text, limit):
    """글자 수 제한에 맞게 자르고, 잘랐으면 끝에 … 을 붙인다."""
    text = text or ""
    return text if len(text) <= limit else text[:limit - 1] + "…"


def build_embed(i, r):
    """글 하나를 디스코드 카드(embed)로 만든다."""
    lines = ["**핵심 요약**"] + [f"• {s}" for s in r["summary"]]
    if r.get("comments"):
        lines += ["", "**댓글 요약**"]
        lines += [f"• **{c['author']}**: {cut(c['summary'], 300)}" for c in r["comments"]]
    if r.get("notion_url"):
        lines += ["", f"📝 [Notion에서 전체 번역 보기]({r['notion_url']})"]

    embed = {
        "title": cut(f"{i}. {r['title_ko']}", 256),
        "url": r["permalink"],
        "description": cut("\n".join(lines), 3500),
        "color": SOURCE_COLORS.get(r.get("source"), 0x888888),
        "fields": [
            {"name": "출처", "value": cut(r["community"], 1024), "inline": True},
            {"name": "유용도", "value": f"{r['usefulness']}/10", "inline": True},
        ],
        "footer": {"text": cut(f"{byline(r)}\n원제: {r['original_title']}", 2048)},
    }
    if r.get("tags"):
        embed["fields"].append({"name": "태그", "value": cut(", ".join(r["tags"]), 1024), "inline": True})
    return embed


def embed_size(embed):
    """디스코드가 세는 방식대로 카드 하나의 글자 수를 센다."""
    size = len(embed.get("title", "")) + len(embed.get("description", "")) + len(embed["footer"]["text"])
    size += sum(len(f["name"]) + len(f["value"]) for f in embed.get("fields", []))
    return size


def group_embeds(embeds):
    """카드들을 메시지 하나에 들어갈 만큼씩 묶는다 (10장, 5500자 이하)."""
    groups, current, chars = [], [], 0
    for e in embeds:
        size = embed_size(e)
        if current and (len(current) >= MAX_EMBEDS_PER_MESSAGE or chars + size > MAX_CHARS_PER_MESSAGE):
            groups.append(current)
            current, chars = [], 0
        current.append(e)
        chars += size
    if current:
        groups.append(current)
    return groups


def post(webhook_url, payload, file_path=None, retries=3):
    """웹훅으로 메시지 하나를 보낸다. 요청 제한(429)이면 알려 준 시간만큼 기다렸다 재시도."""
    for attempt in range(retries + 1):
        if file_path:
            # 파일을 첨부할 때는 내용(JSON)과 파일을 함께 보내는 형식(multipart)을 씀
            with open(file_path, "rb") as f:
                resp = requests.post(
                    webhook_url,
                    data={"payload_json": json.dumps(payload, ensure_ascii=False)},
                    files={"files[0]": (Path(file_path).name, f, "application/pdf")},
                    timeout=60,
                )
        else:
            resp = requests.post(webhook_url, json=payload, timeout=30)

        if resp.status_code == 429 and attempt < retries:
            wait = float(resp.json().get("retry_after", 2))
            log.warning("디스코드 요청 제한, %.1f초 기다립니다.", wait)
            time.sleep(wait + 0.5)
            continue
        if resp.status_code >= 400:
            raise RuntimeError(f"디스코드 전송 실패 ({resp.status_code}): {resp.text[:300]}")
        time.sleep(1)  # 연속으로 보낼 때 요청 제한에 걸리지 않게 잠깐 쉼
        return


def send_digest(webhook_url, results, pdf_path, day, username="게임개발 다이제스트", attach_pdf=True):
    """오늘의 다이제스트를 디스코드 채널에 올린다."""
    header = {
        "username": username,
        "content": f"📚 **{TITLE}** {day} · 오늘의 글 {len(results)}개",
        "allowed_mentions": {"parse": []},  # 글 안의 @everyone 같은 것이 실제 알림을 보내지 않게
    }
    file_path = None
    if attach_pdf and pdf_path and Path(pdf_path).exists():
        if Path(pdf_path).stat().st_size <= MAX_FILE_BYTES:
            file_path = pdf_path
        else:
            header["content"] += "\n(PDF가 10MB를 넘어서 첨부하지 못했습니다. 메일을 확인하세요.)"
    post(webhook_url, header, file_path)

    embeds = [build_embed(i, r) for i, r in enumerate(results, 1)]
    for group in group_embeds(embeds):
        post(webhook_url, {"username": username, "embeds": group, "allowed_mentions": {"parse": []}})
