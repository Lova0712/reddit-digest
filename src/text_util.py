"""
HTML 을 읽기 쉬운 일반 텍스트로 바꾸는 도구 (파이썬 기본 html.parser 사용).

Reddit RSS 와 Stack Exchange 는 본문을 HTML 로 주기 때문에,
번역·PDF·Notion 에서 쓰기 좋게 아래처럼 바꿉니다.
- 문단/줄바꿈 태그 → 빈 줄
- 목록 <li> → "- " 로 시작하는 줄
- 코드 <pre> → ``` 로 감싼 코드 블록 (다른 모듈이 코드 블록으로 표시)
- 링크 → "글자 (주소)"
- 이미지 → [이미지]
"""

import re
from html import unescape
from html.parser import HTMLParser

BLOCK_TAGS = {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "tr", "hr", "table"}


class _TextMaker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.in_pre = 0
        self.link = None  # 현재 열린 <a> 의 (주소, 시작 위치)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "pre":
            self.in_pre += 1
            self.out.append("\n\n```\n")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag in BLOCK_TAGS:
            self.out.append("\n" if tag == "br" else "\n\n")
        elif tag == "a":
            self.link = (attrs.get("href") or "", len(self.out))
        elif tag == "img":
            self.out.append("[이미지]")

    def handle_endtag(self, tag):
        if tag == "pre":
            self.in_pre -= 1
            self.out.append("\n```\n\n")
        elif tag in BLOCK_TAGS:
            self.out.append("\n\n")
        elif tag == "a" and self.link:
            href, start = self.link
            text = "".join(self.out[start:]).strip()
            # 링크 글자와 주소가 다를 때만 주소를 괄호로 덧붙임
            if href.startswith("http") and text and text != href:
                self.out.append(f" ({href})")
            self.link = None

    def handle_data(self, data):
        if not self.in_pre:
            data = re.sub(r"\s+", " ", data)  # 코드 밖에서는 연속 공백을 하나로
        self.out.append(data)


def html_to_text(html):
    """HTML 문자열을 일반 텍스트로 바꾼다."""
    if not html:
        return ""
    maker = _TextMaker()
    maker.feed(html)
    maker.close()
    text = "".join(maker.out)
    text = re.sub(r"[ \t]+\n", "\n", text)       # 줄 끝 공백 제거
    text = re.sub(r"\n{3,}", "\n\n", text)       # 빈 줄은 최대 1개
    return text.strip()


def count_text(r):
    """'추천 37 · 댓글 5' 처럼 반응 수를 글로. 수치를 모르는 출처(Reddit RSS)는 빈 문자열."""
    if r.get("score") is None:
        return ""
    return f"추천 {r['score']} · 댓글 {r.get('num_comments') or 0}"


def byline(r):
    """출처 · 작성자 · 작성일 (· 추천 · 댓글) 한 줄 요약. PDF·Notion·메일에서 공통으로 사용."""
    parts = [r["community"], r["author"], f"작성일 {r['created_date']}"]
    if count_text(r):
        parts.append(count_text(r))
    return " · ".join(parts)


def clean_title(title):
    """&amp; 같은 HTML 특수문자 표기를 원래 글자로 바꾼다."""
    return unescape(title or "").strip()
