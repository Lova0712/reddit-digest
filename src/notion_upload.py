"""
번역 결과를 Notion 데이터베이스에 글 1개당 페이지 1개로 올리는 모듈 (notion-client 사용).

Notion API 제한 대응
- 글자 조각(rich_text) 하나에 최대 2000자 → 자동으로 잘라서 여러 조각으로
- 한 번 요청에 블록(문단 등) 최대 100개 → 100개씩 나눠서 추가
- 요청이 너무 많으면(429) 잠시 기다렸다가 다시 시도

Notion API 2025-09-03 버전부터 "데이터베이스" 안에 "데이터 소스"가 있고,
페이지는 데이터 소스에 만들어야 합니다. .env 에는 데이터베이스 ID 만 적어 두고
데이터 소스 ID 는 실행할 때 찾아서 씁니다.
"""

import logging
import re
import time

from notion_client import APIResponseError, Client

from src.text_util import byline
from src.translate import TAG_OPTIONS

log = logging.getLogger(__name__)

MAX_TEXT = 2000       # rich_text 조각 하나의 최대 글자 수
MAX_BLOCKS = 100      # 요청 한 번에 보낼 수 있는 최대 블록 수
REQUEST_GAP = 0.4     # 요청 사이 대기 (Notion 권장: 초당 약 3회 이하)

DATABASE_TITLE = "게임개발 커뮤니티 다이제스트"

# 데이터베이스 칸(속성) 구성 - setup_notion.py 에서 이 모양으로 만듭니다.
# "출처" 선택지는 처음 보는 이름이 오면 Notion 이 자동으로 추가합니다.
PROPERTIES = {
    "제목": {"title": {}},
    "출처": {"select": {"options": [
        {"name": "r/gamedev", "color": "orange"},
        {"name": "r/indiedev", "color": "orange"},
        {"name": "r/Unity3D", "color": "orange"},
        {"name": "dev.to #gamedev", "color": "purple"},
        {"name": "dev.to #unity3d", "color": "purple"},
        {"name": "GameDev SE", "color": "blue"},
    ]}},
    "원문 링크": {"url": {}},
    "점수": {"number": {"format": "number"}},
    "유용도": {"number": {"format": "number"}},
    "태그": {"multi_select": {"options": [{"name": t} for t in TAG_OPTIONS]}},
    "날짜": {"date": {}},
    "작성자": {"rich_text": {}},
}

# 코드 블록 언어 표시 → Notion 이 아는 언어 이름
CODE_LANGUAGES = {
    "csharp": "c#", "cs": "c#", "c#": "c#", "cpp": "c++", "c++": "c++", "c": "c",
    "python": "python", "py": "python", "js": "javascript", "javascript": "javascript",
    "ts": "typescript", "typescript": "typescript", "json": "json", "gdscript": "plain text",
    "lua": "lua", "java": "java", "rust": "rust", "go": "go", "bash": "bash", "shell": "shell",
}


def make_client(token):
    return Client(auth=token)


def page_id_from_url(url):
    """Notion 페이지 링크에서 32자리 ID 를 꺼낸다."""
    match = re.search(r"([0-9a-f]{32})(?:\?|$)", url.replace("-", ""))
    if not match:
        raise ValueError(f"Notion 페이지 ID를 찾을 수 없습니다: {url}")
    return match.group(1)


def call(func, *args, retries=3, **kwargs):
    """Notion 요청을 보내고, 요청 제한(429)·서버 에러면 기다렸다가 다시 시도한다."""
    for attempt in range(retries + 1):
        try:
            result = func(*args, **kwargs)
            time.sleep(REQUEST_GAP)
            return result
        except APIResponseError as e:
            if e.status not in (429, 500, 502, 503, 504) or attempt == retries:
                raise
            wait = 2 * (2 ** attempt)
            log.warning("Notion 요청 실패(%s), %d초 후 다시 시도합니다.", e.status, wait)
            time.sleep(wait)


# ───────────── 데이터베이스 만들기 (처음 한 번) ─────────────

def create_database(client, page_id):
    """지정한 Notion 페이지 안에 다이제스트용 데이터베이스를 만들고 ID 를 돌려준다."""
    db = call(
        client.databases.create,
        parent={"type": "page_id", "page_id": page_id},
        title=[{"type": "text", "text": {"content": DATABASE_TITLE}}],
        is_inline=True,  # 페이지 안에 표로 바로 보이게
        initial_data_source={"properties": PROPERTIES},
    )
    return db["id"]


def get_data_source_id(client, database_id):
    """데이터베이스 ID 로 실제 페이지를 넣을 데이터 소스 ID 를 찾는다."""
    db = call(client.databases.retrieve, database_id=database_id)
    sources = db.get("data_sources") or []
    if not sources:
        raise RuntimeError("Notion 데이터베이스에 데이터 소스가 없습니다.")
    return sources[0]["id"]


# 예전 이름 → 새 이름 (Reddit 만 쓰던 시절의 "서브레딧" 칸을 "출처"로)
RENAMED_PROPERTIES = {"서브레딧": "출처"}


def ensure_schema(client, data_source_id):
    """
    데이터베이스 칸 구성이 지금 코드와 맞는지 확인하고, 다르면 고친다.
    - 예전 이름의 칸은 새 이름으로 바꾸고 (기존 값 유지)
    - 없는 칸은 추가한다
    """
    ds = call(client.data_sources.retrieve, data_source_id=data_source_id)
    existing = set(ds.get("properties", {}))
    changes = {}
    for old, new in RENAMED_PROPERTIES.items():
        if old in existing and new not in existing:
            changes[old] = {"name": new}
            existing.add(new)
    for name, spec in PROPERTIES.items():
        if name not in existing and name != "제목":
            changes[name] = spec
    if changes:
        call(client.data_sources.update, data_source_id=data_source_id, properties=changes)
        log.info("Notion 데이터베이스 칸 구성을 갱신했습니다: %s", ", ".join(changes))


# ───────────── 글자·블록 만들기 ─────────────

def split_text(text, size=MAX_TEXT):
    """긴 글을 size 글자씩 자른다."""
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]


def rich_text(text, bold=False, link=None):
    """글자를 Notion rich_text 조각 목록으로 만든다. 2000자가 넘으면 여러 조각으로."""
    parts = []
    for chunk in split_text(text):
        item = {"type": "text", "text": {"content": chunk}}
        if link:
            item["text"]["link"] = {"url": link}
        if bold:
            item["annotations"] = {"bold": True}
        parts.append(item)
    return parts


def md_rich_text(text):
    """**굵게** 표시를 실제 굵은 글씨로 바꿔서 rich_text 로 만든다."""
    parts = []
    for i, piece in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if piece:
            parts += rich_text(piece, bold=(i % 2 == 1))
    return parts[:100] or rich_text("")  # 블록 하나에 조각은 최대 100개


def block(kind, parts):
    return {"object": "block", "type": kind, kind: {"rich_text": parts}}


def heading(text):
    return block("heading_2", rich_text(text))


def paragraph(text):
    return block("paragraph", md_rich_text(text))


def bullet(parts):
    return block("bulleted_list_item", parts)


def code(text, lang=""):
    language = CODE_LANGUAGES.get(lang.lower().strip(), "plain text")
    return {"object": "block", "type": "code",
            "code": {"rich_text": rich_text(text.strip("\n")), "language": language}}


def body_blocks(text):
    """번역 본문을 문단·코드 블록으로 나눈다. ``` 로 감싼 부분은 코드 블록."""
    blocks = []
    # ```언어\n코드``` 를 통째로 잘라낸다 → [글, 언어, 코드, 글, 언어, 코드, 글 ...]
    pieces = re.split(r"```([^\n]*)\n(.*?)```", text, flags=re.S)
    for i in range(0, len(pieces), 3):
        for para in re.split(r"\n\s*\n", pieces[i]):
            if para.strip():
                blocks.append(paragraph(para.strip()))
        if i + 2 < len(pieces) and pieces[i + 2].strip():
            blocks.append(code(pieces[i + 2], pieces[i + 1]))
    return blocks


def build_blocks(r):
    """페이지 본문: 원문 정보 → 요약 → 번역 → 댓글 요약."""
    info = (
        rich_text("원문: ", bold=True) + rich_text(r["permalink"], link=r["permalink"])
        + rich_text(f"\n{r['original_title']}\n{byline(r)}")
    )
    blocks = [{"object": "block", "type": "callout",
               "callout": {"rich_text": info, "icon": {"type": "emoji", "emoji": "🔗"}, "color": "gray_background"}}]

    blocks.append(heading("핵심 요약"))
    blocks += [bullet(md_rich_text(s)) for s in r["summary"]]

    blocks.append(heading("본문 번역"))
    blocks += body_blocks(r["body_ko"])

    blocks.append(heading("댓글 요약"))
    if r["comments"]:
        for c in r["comments"]:
            blocks.append(bullet(rich_text(c["author"], bold=True) + rich_text(": ") + md_rich_text(c["summary"])))
    else:
        blocks.append(paragraph("(유용한 댓글 없음)"))
    return blocks


def build_properties(r, digest_date):
    return {
        "제목": {"title": rich_text(r["title_ko"])},
        "출처": {"select": {"name": r["community"]}},
        "원문 링크": {"url": r["permalink"]},
        "점수": {"number": r.get("score")},  # Reddit RSS 는 추천 수가 없어 빈칸
        "유용도": {"number": r.get("usefulness")},
        "태그": {"multi_select": [{"name": t} for t in r["tags"]]},
        "날짜": {"date": {"start": digest_date}},  # 다이제스트로 수집한 날
        "작성자": {"rich_text": rich_text(r["author"])},
    }


# ───────────── 업로드 ─────────────

def find_existing(client, data_source_id, permalink):
    """같은 원문 링크의 페이지가 이미 있으면 그 페이지 주소, 없으면 None (재시도 때 중복 생성 방지)."""
    res = call(
        client.data_sources.query,
        data_source_id=data_source_id,
        filter={"property": "원문 링크", "url": {"equals": permalink}},
        page_size=1,
    )
    results = res.get("results") or []
    return (results[0].get("url") or "") if results else None


def upload_post(client, data_source_id, r, digest_date):
    """글 하나를 Notion 페이지로 만들고 페이지 주소를 돌려준다. 이미 있으면 새로 만들지 않고 그 주소를 돌려준다."""
    existing = find_existing(client, data_source_id, r["permalink"])
    if existing is not None:
        log.info("Notion에 이미 있음, 건너뜀: %s", r["title_ko"][:40])
        return existing

    blocks = build_blocks(r)
    page = call(
        client.pages.create,
        parent={"type": "data_source_id", "data_source_id": data_source_id},
        properties=build_properties(r, digest_date),
        children=blocks[:MAX_BLOCKS],
    )
    # 블록이 100개를 넘으면 나머지를 100개씩 이어 붙인다
    for start in range(MAX_BLOCKS, len(blocks), MAX_BLOCKS):
        call(client.blocks.children.append, block_id=page["id"], children=blocks[start:start + MAX_BLOCKS])
    log.info("Notion 업로드: %s", r["title_ko"][:40])
    return page.get("url") or ""
