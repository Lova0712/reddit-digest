"""
3단계(PDF) 테스트. 외부 API 없이 가짜 번역 결과로 PDF 를 만들어 본다.
실행: python -m pytest
"""

from pathlib import Path

from reportlab.pdfbase import pdfmetrics

from src import pdf_maker

ROOT = Path(__file__).parent.parent
REGULAR = ROOT / "fonts" / "NotoSansKR-Regular.ttf"
BOLD = ROOT / "fonts" / "NotoSansKR-Bold.ttf"


def fake_result(i):
    return {
        "id": f"t{i}",
        "source": "reddit_rss",
        "community": "r/gamedev",
        "author": "tester",
        "created_date": "2026-09-29",
        "permalink": f"https://www.reddit.com/r/gamedev/comments/t{i}/",
        "score": None,  # Reddit RSS 처럼 추천 수를 모르는 경우
        "num_comments": None,
        "usefulness": 8,
        "original_title": "Use ObjectPool<T> & save GC",  # 특수문자 < > & 가 있어도 깨지면 안 됨
        "title_ko": f"테스트 글 {i}: 오브젝트 풀링(Object Pooling)",
        "summary": ["첫 번째 요약", "**굵은** 요약"],
        "body_ko": "첫 문단입니다.\n\n```csharp\nvar pool = new ObjectPool<Bullet>();\n```\n\n마지막 문단.",
        "comments": [{"author": "c1", "summary": "좋은 댓글"}],
        "tags": ["Unity"],
    }


def test_make_pdf_creates_file(tmp_path):
    path = pdf_maker.make_pdf([fake_result(1), fake_result(2)], tmp_path, "2026-09-29", REGULAR, BOLD)
    assert path.name == "reddit-digest-2026-09-29.pdf"
    data = path.read_bytes()
    assert data.startswith(b"%PDF")
    # 한글 폰트가 PDF 안에 들어갔는지 확인 (없으면 한글이 깨짐)
    assert b"NotoSansKR" in data
    assert pdf_maker.FONT in pdfmetrics.getRegisteredFontNames()


def test_make_pdf_with_no_posts(tmp_path):
    path = pdf_maker.make_pdf([], tmp_path, "2026-09-29", REGULAR, BOLD)
    assert path.exists()


def test_body_splits_code_blocks():
    styles = pdf_maker.make_styles()
    flows = pdf_maker.body_flowables("문단1\n\n```cs\nint a = 1;\n```\n문단2", styles)
    assert [f.style.name for f in flows] == ["body", "code", "body"]
