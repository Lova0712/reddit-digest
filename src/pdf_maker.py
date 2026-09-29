"""
번역 결과를 하루치 PDF 한 파일로 만드는 모듈 (reportlab 사용).

구성: 표지(날짜, 글 개수) → 목차(페이지 번호) → 글별 섹션
파일명: reddit-digest-YYYY-MM-DD.pdf

한글이 깨지지 않도록 fonts/ 폴더의 Noto Sans KR 폰트를 등록해서 모든 글자에 사용합니다.
"""

import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

from src.text_util import byline

TITLE = "게임개발 커뮤니티 다이제스트"
FONT = "NotoSansKR"
FONT_BOLD = "NotoSansKR-Bold"

# 색상
GREY = colors.HexColor("#666666")
LIGHT = colors.HexColor("#F3F4F6")
ACCENT = colors.HexColor("#D9480F")  # Reddit 느낌의 주황
LINK = colors.HexColor("#1C64F2")

MARGIN = 20 * mm
CONTENT_WIDTH = A4[0] - 2 * MARGIN  # 본문 폭 (A4 너비 - 좌우 여백)


def register_fonts(regular_path, bold_path):
    """한글 폰트를 reportlab 에 등록한다. 여러 번 불러도 괜찮다."""
    if FONT in pdfmetrics.getRegisteredFontNames():
        return
    for path in (regular_path, bold_path):
        if not Path(path).exists():
            raise FileNotFoundError(f"폰트 파일이 없습니다: {path} (fonts/README.txt 참고)")
    pdfmetrics.registerFont(TTFont(FONT, str(regular_path)))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(bold_path)))
    # <b> 태그를 쓰면 굵은 폰트가 쓰이도록 묶어 둔다
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_BOLD, italic=FONT, boldItalic=FONT_BOLD)


def make_styles():
    """글자 크기·간격 등 모양 설정 모음."""
    base = dict(fontName=FONT, fontSize=10.5, leading=17)
    return {
        "cover_title": ParagraphStyle("cover_title", fontName=FONT_BOLD, fontSize=26, leading=34,
                                      alignment=TA_CENTER, spaceAfter=14),
        "cover_sub": ParagraphStyle("cover_sub", fontName=FONT, fontSize=13, leading=20,
                                    alignment=TA_CENTER, textColor=GREY),
        "toc_title": ParagraphStyle("toc_title", fontName=FONT_BOLD, fontSize=18, leading=24, spaceAfter=12),
        "post_title": ParagraphStyle("post_title", fontName=FONT_BOLD, fontSize=16, leading=23, spaceAfter=4),
        "original": ParagraphStyle("original", fontName=FONT, fontSize=9.5, leading=14, textColor=GREY,
                                   spaceAfter=6),
        "meta": ParagraphStyle("meta", fontName=FONT, fontSize=9, leading=14, textColor=GREY,
                               wordWrap="CJK"),  # 긴 주소도 줄바꿈되도록
        "h2": ParagraphStyle("h2", fontName=FONT_BOLD, fontSize=12, leading=18, textColor=ACCENT,
                             spaceBefore=12, spaceAfter=4,
                             keepWithNext=1),  # 소제목만 페이지 끝에 혼자 남지 않게
        "body": ParagraphStyle("body", spaceAfter=7, **base),
        "bullet": ParagraphStyle("bullet", leftIndent=12, bulletIndent=2, spaceAfter=3, **base),
        "code": ParagraphStyle("code", fontName=FONT, fontSize=8.5, leading=12.5, wordWrap="CJK",
                               backColor=LIGHT, borderPadding=6, leftIndent=6, rightIndent=6,
                               spaceBefore=8, spaceAfter=16),
        "toc1": ParagraphStyle("toc1", fontName=FONT, fontSize=10.5, leading=17, leftIndent=0),
    }


# ───────────── 본문 텍스트 → 문단 ─────────────

def inline(text):
    """
    일반 텍스트를 reportlab 문단용으로 바꾼다.
    - <, >, & 같은 특수문자는 이스케이프 (예: ObjectPool<T> 가 태그로 오해받지 않게)
    - **굵게** 표시는 실제 굵은 글씨로
    - 한 줄 바꿈은 <br/> 로
    """
    text = escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return text.replace("\n", "<br/>")


def code_block(code, style):
    """코드 블록: 공백과 줄바꿈을 그대로 살려서 회색 상자에 표시."""
    code = escape(code.strip("\n")).replace(" ", "&nbsp;").replace("\n", "<br/>")
    return Paragraph(code, style)


def body_flowables(text, styles):
    """번역 본문을 문단·코드 블록 목록으로 나눈다. ``` 로 감싼 부분은 코드."""
    flows = []
    parts = re.split(r"```[^\n]*\n?", text)
    for i, part in enumerate(parts):
        if i % 2 == 1:  # 홀수 번째 조각 = ``` 안쪽 = 코드
            if part.strip():
                flows.append(code_block(part, styles["code"]))
            continue
        for para in re.split(r"\n\s*\n", part):  # 빈 줄 기준으로 문단 나누기
            if para.strip():
                flows.append(Paragraph(inline(para.strip()), styles["body"]))
    return flows


# ───────────── 목차 연결 ─────────────

class DigestDoc(BaseDocTemplate):
    """글 제목이 나올 때마다 목차와 PDF 책갈피에 등록하는 문서."""

    def __init__(self, path, **kwargs):
        super().__init__(str(path), pagesize=A4,
                         leftMargin=20 * mm, rightMargin=20 * mm, topMargin=20 * mm, bottomMargin=20 * mm,
                         **kwargs)
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="main")
        self.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=draw_footer)])

    def afterFlowable(self, flowable):
        key = getattr(flowable, "toc_key", None)
        if key:
            text = flowable.toc_text
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=0)
            self.notify("TOCEntry", (0, escape(text), self.page, key))


def draw_footer(canvas, doc):
    """모든 페이지 아래에 쪽 번호와 출처 안내를 넣는다."""
    canvas.saveState()
    canvas.setFont(FONT, 8)
    canvas.setFillColor(GREY)
    canvas.drawString(20 * mm, 10 * mm, "개인 학습용 번역 · 원문 저작권은 각 작성자에게 있습니다")
    canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, str(doc.page))
    canvas.restoreState()


# ───────────── PDF 만들기 ─────────────

def cover_page(results, day, styles):
    communities = sorted({r["community"] for r in results})
    flows = [
        Spacer(1, 70 * mm),
        Paragraph(TITLE, styles["cover_title"]),
        Paragraph(day, styles["cover_sub"]),
        Spacer(1, 6 * mm),
        Paragraph(f"오늘의 글 {len(results)}개", styles["cover_sub"]),
    ]
    if communities:
        flows.append(Paragraph(" · ".join(escape(c) for c in communities), styles["cover_sub"]))
    flows.append(PageBreak())
    return flows


def post_section(i, r, styles):
    """글 하나의 섹션: 제목 → 원문 정보 → 요약 → 번역 → 댓글."""
    title = Paragraph(f"{i}. {inline(r['title_ko'])}", styles["post_title"])
    title.toc_key = f"post{i}"  # 목차에 등록할 표시
    title.toc_text = f"{i}. {r['title_ko']}"

    meta = f"{escape(byline(r))} · 유용도 {r['usefulness']}/10"
    if r.get("tags"):
        meta += " · " + ", ".join(escape(t) for t in r["tags"])
    link = escape(r["permalink"])

    flows = [
        title,
        Paragraph(inline(r["original_title"]), styles["original"]),
        Paragraph(meta, styles["meta"]),
        Paragraph(f'원문: <a href="{link}" color="#1C64F2">{link}</a>', styles["meta"]),
        Spacer(1, 3 * mm),
    ]

    # 핵심 요약은 회색 상자 안에
    summary = [Paragraph(inline(s), styles["bullet"], bulletText="•") for s in r["summary"]]
    box = Table([[summary]], colWidths=[CONTENT_WIDTH])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    flows += [Paragraph("핵심 요약", styles["h2"]), box]

    flows.append(Paragraph("본문 번역", styles["h2"]))
    flows += body_flowables(r["body_ko"], styles)

    flows.append(Paragraph("댓글 요약", styles["h2"]))
    if r["comments"]:
        for c in r["comments"]:
            flows.append(Paragraph(f"<b>{escape(c['author'])}</b>: {inline(c['summary'])}",
                                   styles["bullet"], bulletText="•"))
    else:
        flows.append(Paragraph("(유용한 댓글 없음)", styles["body"]))
    return flows


def make_pdf(results, out_dir, day, regular_font, bold_font):
    """
    results : translate.translate_post() 결과 목록
    day     : "YYYY-MM-DD"
    만든 PDF 파일 경로를 돌려준다.
    """
    register_fonts(regular_font, bold_font)
    styles = make_styles()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"reddit-digest-{day}.pdf"

    story = cover_page(results, day, styles)

    # 목차
    toc = TableOfContents()
    toc.levelStyles = [styles["toc1"]]
    toc.dotsMinLevel = 0
    story += [Paragraph("목차", styles["toc_title"]), toc, PageBreak()]

    if not results:
        story.append(Paragraph("오늘은 기준을 넘은 글이 없습니다.", styles["body"]))
    for i, r in enumerate(results, 1):
        if i > 1:
            story.append(PageBreak())  # 글마다 새 페이지에서 시작 (마지막 빈 페이지 방지)
        story += post_section(i, r, styles)

    doc = DigestDoc(path, title=f"{TITLE} {day}", author="reddit-digest")
    # 목차의 페이지 번호를 채우려면 두 번 이상 조판해야 해서 multiBuild 사용
    doc.multiBuild(story)
    return path
