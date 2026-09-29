"""
4단계(Notion) 테스트. 실제 Notion 대신 가짜 클라이언트를 사용합니다.
실행: python -m pytest
"""

from src import notion_upload
from src.store import Store


def fake_result(body="본문입니다."):
    return {
        "id": "devto:1", "source": "devto", "community": "dev.to #gamedev", "author": "tester",
        "created_date": "2026-09-29", "permalink": "https://dev.to/tester/t1", "score": 37, "num_comments": 5,
        "usefulness": 8,
        "original_title": "Original", "title_ko": "테스트 글", "summary": ["요약1", "**굵게** 요약2"],
        "body_ko": body, "comments": [{"author": "c1", "summary": "댓글"}], "tags": ["Unity"],
    }


class FakeEndpoint:
    def __init__(self, log, name, response):
        self.log, self.name, self.response = log, name, response

    def __call__(self, **kwargs):
        self.log.append((self.name, kwargs))
        return self.response


class FakeClient:
    """notion-client 와 같은 모양의 가짜. 어떤 요청이 갔는지 calls 에 기록한다."""

    def __init__(self, existing=False):
        self.calls = []
        self.pages = type("P", (), {})()
        self.pages.create = FakeEndpoint(self.calls, "pages.create", {"id": "page1", "url": "https://notion.so/page1"})
        self.data_sources = type("D", (), {})()
        self.data_sources.query = FakeEndpoint(self.calls, "query",
                                               {"results": [{"url": "https://notion.so/old"}] if existing else []})
        self.blocks = type("B", (), {})()
        self.blocks.children = type("C", (), {})()
        self.blocks.children.append = FakeEndpoint(self.calls, "append", {})


def test_page_id_from_url():
    url = "https://app.notion.com/p/Reddit-3e9053e4182c8011b4e9d5dc6c0443c4?source=copy_link"
    assert notion_upload.page_id_from_url(url) == "3e9053e4182c8011b4e9d5dc6c0443c4"


def test_rich_text_splits_at_2000_chars():
    parts = notion_upload.rich_text("가" * 4500)
    assert [len(p["text"]["content"]) for p in parts] == [2000, 2000, 500]


def test_bold_markdown():
    parts = notion_upload.md_rich_text("앞 **굵게** 뒤")
    assert [(p["text"]["content"], p.get("annotations", {}).get("bold", False)) for p in parts] == [
        ("앞 ", False), ("굵게", True), (" 뒤", False)]


def test_body_blocks_with_code():
    blocks = notion_upload.body_blocks("문단1\n\n```csharp\nint a = 1;\n```\n\n문단2")
    assert [b["type"] for b in blocks] == ["paragraph", "code", "paragraph"]
    assert blocks[1]["code"]["language"] == "c#"


def test_upload_splits_more_than_100_blocks(monkeypatch):
    monkeypatch.setattr(notion_upload, "REQUEST_GAP", 0)
    body = "\n\n".join(f"문단 {i}" for i in range(250))  # 블록 250개 이상
    client = FakeClient()
    url = notion_upload.upload_post(client, "ds1", fake_result(body), "2026-09-29")
    assert url == "https://notion.so/page1"
    create = [kw for name, kw in client.calls if name == "pages.create"][0]
    appends = [kw for name, kw in client.calls if name == "append"]
    assert len(create["children"]) == 100
    assert all(len(a["children"]) <= 100 for a in appends)
    total = len(create["children"]) + sum(len(a["children"]) for a in appends)
    assert total == len(notion_upload.build_blocks(fake_result(body)))


def test_upload_skips_existing(monkeypatch):
    monkeypatch.setattr(notion_upload, "REQUEST_GAP", 0)
    client = FakeClient(existing=True)
    # 새로 만들지 않고, 이미 있는 페이지 주소를 돌려준다 (디스코드 링크용)
    assert notion_upload.upload_post(client, "ds1", fake_result(), "2026-09-29") == "https://notion.so/old"
    assert not [c for c in client.calls if c[0] == "pages.create"]


def test_store_keeps_translation_for_retry(tmp_path):
    store = Store(tmp_path / "t.db")
    store.save_translation(fake_result())
    assert store.is_processed("devto:1")
    assert store.pending_translations()[0]["title_ko"] == "테스트 글"
    store.mark("devto:1", "done")
    assert store.pending_translations() == []
    store.close()


def test_ensure_schema_renames_old_column(monkeypatch):
    """예전 '서브레딧' 칸이 있으면 '출처'로 이름을 바꾼다."""
    monkeypatch.setattr(notion_upload, "REQUEST_GAP", 0)
    client = FakeClient()
    old_props = {name: {} for name in notion_upload.PROPERTIES if name != "출처"}
    old_props["서브레딧"] = {}
    client.data_sources.retrieve = FakeEndpoint(client.calls, "retrieve", {"properties": old_props})
    client.data_sources.update = FakeEndpoint(client.calls, "update", {})
    notion_upload.ensure_schema(client, "ds1")
    update = [kw for name, kw in client.calls if name == "update"][0]
    assert update["properties"] == {"서브레딧": {"name": "출처"}}


def test_properties_with_unknown_score():
    r = dict(fake_result(), score=None, community="r/gamedev")
    props = notion_upload.build_properties(r, "2026-09-29")
    assert props["점수"] == {"number": None}
    assert props["출처"] == {"select": {"name": "r/gamedev"}}
