from pathlib import Path
import re
from io import BytesIO

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except ImportError:  # pragma: no cover - the bundled runtime normally has Pillow
    Image = ImageDraw = ImageFont = ImageOps = None


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(r"C:\Users\isach\Downloads\專題系統文件書 (1).docx")
# 目前上一版正式檔正在預覽，因此先輸出不覆蓋舊檔的新正式版。
OUTPUT = ROOT / "專題系統文件書_妝識你的美_初版格式_整合模型Worker前端演算法與Ollama_2026-09-06.docx"
FIGURES = ROOT / "docs" / "figures"
USER_FACE_ACTIVITY = FIGURES / "face-analysis-activity-user.png"
USER_GATEWAY_SWIMLANE = FIGURES / "gateway-frontend-swimlane-user.png"
ALGORITHM_FLOW_SOURCE = FIGURES / "algorithm_supplement_1.png"
ALGORITHM_ACTIVITY_SOURCE = FIGURES / "algorithm_supplement_2.png"
ALGORITHM_FLOW = FIGURES / "商品推薦系統整體流程圖_黑白.png"
ALGORITHM_ACTIVITY = FIGURES / "個人化推薦演算法活動圖_黑白.png"


def set_run_font_family(run, east_asia="標楷體", latin="Times New Roman"):
    """中文使用標楷體；英文、數字與拉丁字元使用 Times New Roman。"""
    run.font.name = latin
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    for attr in ("ascii", "hAnsi", "cs"):
        rfonts.set(qn(f"w:{attr}"), latin)
    rfonts.set(qn("w:eastAsia"), east_asia)


def font_run(run, size=12, bold=False, name="標楷體"):
    set_run_font_family(run, east_asia=name)
    run.font.size = Pt(size)
    run.bold = bold
    run.font.color.rgb = RGBColor(0, 0, 0)


def set_margins(cell, top=90, start=100, bottom=90, end=100):
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for name, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{name}"))
        if node is None:
            node = OxmlElement(f"w:{name}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def clear_cell(cell):
    cell.text = ""
    return cell.paragraphs[0]


def cell_text(cell, text, bold=False, size=12):
    p = clear_cell(cell)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.0
    run = p.add_run(str(text))
    # 報告內文規格統一為 12pt；size 保留在函式介面，避免既有呼叫端失效。
    font_run(run, size=12, bold=bold)
    set_margins(cell)


def new_table(doc, headers, rows, widths=None, size=9.5):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = 1
    table.autofit = False
    for i, header in enumerate(headers):
        cell_text(table.rows[0].cells[i], header, bold=True, size=size)
    # 表格跨頁時重複欄名，且避免欄名列單獨落在頁尾。
    header_row = table.rows[0]
    tr_pr = header_row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)
    for cell in header_row.cells:
        for paragraph in cell.paragraphs:
            paragraph.paragraph_format.keep_with_next = True
    for row in rows:
        cells = table.add_row().cells
        for i, value in enumerate(row):
            cell_text(cells[i], value, size=size)
    if widths:
        # 內文版面寬度約 16 cm；把欄寬總和限制在版心內，避免長表格超出版面。
        width_total = sum(widths)
        if width_total > 16.0:
            scale = 16.0 / width_total
            widths = [round(width * scale, 2) for width in widths]
        for row in table.rows:
            for i, width in enumerate(widths):
                row.cells[i].width = Cm(width)
    return table


def new_body(doc, text, elements, indent=True, size=12, bold=False):
    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = 1.0
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.first_line_indent = Cm(0.74) if indent else Cm(0)
    run = p.add_run(text)
    font_run(run, size=size, bold=bold)
    elements.append(p._p)
    return p


def new_heading(doc, text, elements, level=2):
    p = doc.add_paragraph(style=f"Heading {level}")
    p.paragraph_format.keep_with_next = True
    p.paragraph_format.line_spacing = 1.0
    p.paragraph_format.space_before = Pt(10 if level == 1 else 6)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.first_line_indent = Cm(0)
    run = p.add_run(text)
    font_run(run, size=14, bold=True)
    elements.append(p._p)
    return p


def new_bullet(doc, text, elements):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.line_spacing = 1.0
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.first_line_indent = Cm(0)
    run = p.add_run(text)
    font_run(run, size=12)
    elements.append(p._p)
    return p


def new_page_break(doc, elements):
    p = doc.add_paragraph()
    p.add_run().add_break(WD_BREAK.PAGE)
    elements.append(p._p)


def add_toc_line(doc, label, level, elements):
    """用範本的逐行目錄格式：分層、點引線、右側頁碼欄位。"""
    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = 1.0
    p.paragraph_format.space_after = Pt(1)
    p.paragraph_format.left_indent = Cm(0.0 if level == 1 else 0.8 if level == 2 else 1.55)
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.tab_stops.add_tab_stop(Cm(15.4), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
    r = p.add_run(label)
    font_run(r, size=12, bold=level == 1)
    tab = p.add_run("\t")
    font_run(tab, size=12)
    page = p.add_run("—")
    font_run(page, size=12)
    elements.append(p._p)


def add_page_field(paragraph):
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = "1"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend([begin, instr, separate, text, end])
    font_run(run, size=10)


def configure_doc(doc):
    for sec in doc.sections:
        sec.page_width = Cm(21)
        sec.page_height = Cm(29.7)
        sec.top_margin = Cm(2.5)
        sec.bottom_margin = Cm(2.3)
        sec.left_margin = Cm(2.5)
        sec.right_margin = Cm(2.5)
        sec.header_distance = Cm(1.3)
        sec.footer_distance = Cm(1.2)
        fp = sec.footer.paragraphs[0] if sec.footer.paragraphs else sec.footer.add_paragraph()
        fp.text = ""
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add_page_field(fp)

    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal_rfonts = normal._element.rPr.rFonts
    normal_rfonts.set(qn("w:ascii"), "Times New Roman")
    normal_rfonts.set(qn("w:hAnsi"), "Times New Roman")
    normal_rfonts.set(qn("w:cs"), "Times New Roman")
    normal_rfonts.set(qn("w:eastAsia"), "標楷體")
    normal.font.size = Pt(12)
    normal.paragraph_format.line_spacing = 1.0
    normal.paragraph_format.space_after = Pt(0)
    for name, size in (("Heading 1", 14), ("Heading 2", 14), ("Heading 3", 14)):
        style = doc.styles[name]
        style.font.name = "Times New Roman"
        style_rfonts = style._element.rPr.rFonts
        style_rfonts.set(qn("w:ascii"), "Times New Roman")
        style_rfonts.set(qn("w:hAnsi"), "Times New Roman")
        style_rfonts.set(qn("w:cs"), "Times New Roman")
        style_rfonts.set(qn("w:eastAsia"), "標楷體")
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor(0, 0, 0)
    if "Hyperlink" in doc.styles:
        doc.styles["Hyperlink"].font.color.rgb = RGBColor(0, 0, 0)
        doc.styles["Hyperlink"].font.underline = False
    if "Followed Hyperlink" in doc.styles:
        doc.styles["Followed Hyperlink"].font.color.rgb = RGBColor(0, 0, 0)
        doc.styles["Followed Hyperlink"].font.underline = False


def _figure_font(size, bold=False):
    """找 Windows 中文字型；找不到時才退回 Pillow 內建字型。"""
    if ImageFont is None:
        return None
    candidates = [
        r"C:\Windows\Fonts\msjhbd.ttc" if bold else r"C:\Windows\Fonts\msjh.ttc",
        r"C:\Windows\Fonts\mingliub.ttc" if bold else r"C:\Windows\Fonts\mingliu.ttc",
        r"C:\Windows\Fonts\NotoSansCJKtc-Regular.otf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size, index=0)
            except OSError:
                continue
    return ImageFont.load_default()


def _draw_centered(draw, box, text, font, fill=(0, 0, 0), spacing=8):
    left, top, right, bottom = box
    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align="center")
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = left + (right - left - tw) / 2 - bbox[0]
    y = top + (bottom - top - th) / 2 - bbox[1]
    draw.multiline_text((x, y), text, font=font, fill=fill, spacing=spacing, align="center")


def _arrow(draw, start, end, width=5):
    """畫黑白流程箭頭，避免只靠線條看不出方向。"""
    import math

    x1, y1 = start
    x2, y2 = end
    draw.line((x1, y1, x2, y2), fill=(0, 0, 0), width=width)
    angle = math.atan2(y2 - y1, x2 - x1)
    head = 18
    spread = 0.55
    p1 = (x2 - head * math.cos(angle - spread), y2 - head * math.sin(angle - spread))
    p2 = (x2 - head * math.cos(angle + spread), y2 - head * math.sin(angle + spread))
    draw.polygon([(x2, y2), p1, p2], fill=(0, 0, 0))


def _terminator(draw, box, text, font):
    draw.rounded_rectangle(box, radius=35, outline=(0, 0, 0), width=5, fill=(255, 255, 255))
    _draw_centered(draw, box, text, font)


def _process(draw, box, text, font):
    draw.rectangle(box, outline=(0, 0, 0), width=5, fill=(255, 255, 255))
    _draw_centered(draw, box, text, font)


def _io(draw, box, text, font, slant=34):
    left, top, right, bottom = box
    points = [(left + slant, top), (right, top), (right - slant, bottom), (left, bottom)]
    draw.polygon(points, outline=(0, 0, 0), fill=(255, 255, 255))
    draw.line(points + [points[0]], fill=(0, 0, 0), width=5, joint="curve")
    _draw_centered(draw, box, text, font)


def _decision(draw, box, text, font):
    left, top, right, bottom = box
    mid_x = (left + right) // 2
    mid_y = (top + bottom) // 2
    points = [(mid_x, top), (right, mid_y), (mid_x, bottom), (left, mid_y)]
    draw.polygon(points, outline=(0, 0, 0), fill=(255, 255, 255))
    draw.line(points + [points[0]], fill=(0, 0, 0), width=5, joint="curve")
    _draw_centered(draw, (left + 35, top + 22, right - 35, bottom - 22), text, font)


def _database(draw, box, text, font):
    left, top, right, bottom = box
    height = 36
    draw.ellipse((left, top, right, top + height), outline=(0, 0, 0), width=5, fill=(255, 255, 255))
    draw.rectangle((left, top + height // 2, right, bottom - height // 2), outline=(0, 0, 0), width=5, fill=(255, 255, 255))
    draw.arc((left, bottom - height, right, bottom), 0, 180, fill=(0, 0, 0), width=5)
    _draw_centered(draw, (left + 20, top + height, right - 20, bottom - height), text, font)


def create_flowchart_images():
    """產生兩張黑白流程圖，明確表現不同流程圖元素。"""
    if Image is None:
        raise RuntimeError("Bundled Python runtime 缺少 Pillow，無法建立流程圖")
    FIGURES.mkdir(parents=True, exist_ok=True)
    font = _figure_font(34)
    small = _figure_font(27)
    label = _figure_font(23, bold=True)

    # 圖一：從輸入照片到分析、建議、渲染和回饋的整體資料流。
    image = Image.new("RGB", (2400, 1750), "white")
    draw = ImageDraw.Draw(image)
    draw.text((80, 35), "系統資料流程（黑白示意）", font=_figure_font(42, bold=True), fill=(0, 0, 0))
    _terminator(draw, (1000, 100, 1400, 190), "開始", font)
    _io(draw, (890, 250, 1510, 390), "輸入\n使用者照片＋分析需求", font)
    _process(draw, (890, 460, 1510, 600), "Gateway 驗證\n建立 faceJobId / render job", font)
    _process(draw, (890, 670, 1510, 810), "Face Mesh\n關鍵點與 ROI 裁切", font)
    _database(draw, (890, 880, 1510, 1030), "模型、類別、manifest\n與 SHA-256", font)
    _process(draw, (890, 1100, 1510, 1240), "BASIC / PRO 推論\n產生五官分析結果", font)
    _decision(draw, (915, 1310, 1485, 1480), "分析成功？", font)

    _io(draw, (130, 1370, 690, 1510), "否：輸出\n4xx／5xx＋錯誤原因", small)
    _io(draw, (830, 1580, 1570, 1710), "是：輸出 analysisPackage\n結果、版本、信心與 jobId", small)
    _process(draw, (1710, 1370, 2260, 1510), "建議服務／Ollama\n產生結構化文字與簽章", small)
    _io(draw, (1710, 1580, 2260, 1710), "渲染輸入\nimage＋analysisPackage", small)

    for a, b in [((1200, 190), (1200, 250)), ((1200, 390), (1200, 460)), ((1200, 600), (1200, 670)), ((1200, 810), (1200, 880)), ((1200, 1030), (1200, 1100)), ((1200, 1240), (1200, 1310))]:
        _arrow(draw, a, b)
    _arrow(draw, (915, 1395), (690, 1440))
    _arrow(draw, (1200, 1480), (1200, 1580))
    _arrow(draw, (1485, 1395), (1710, 1440))
    _arrow(draw, (1985, 1510), (1985, 1580))
    draw.text((1510, 1320), "是", font=label, fill=(0, 0, 0))
    draw.text((730, 1320), "否", font=label, fill=(0, 0, 0))
    image.save(FIGURES / "系統資料流程圖_黑白.png")

    # 圖二：渲染端的輸入、驗證、非同步工作、資料保存和輸出。
    image = Image.new("RGB", (2500, 1800), "white")
    draw = ImageDraw.Draw(image)
    draw.text((80, 35), "渲染端輸入／輸出與驗證流程（黑白示意）", font=_figure_font(42, bold=True), fill=(0, 0, 0))
    _terminator(draw, (70, 160, 360, 250), "開始", font)
    _io(draw, (430, 110, 990, 300), "輸入：POST /render/jobs\nimage、styleId、strength\nanalysisPackage、faceJobId", small)
    _process(draw, (1080, 145, 1500, 265), "驗證 image\n格式、大小、style", small)
    _decision(draw, (1600, 100, 2020, 310), "輸入有效？", small)
    _io(draw, (2110, 125, 2440, 285), "否：400／413／422\n結構化錯誤", small)

    _process(draw, (430, 430, 990, 600), "組合 prompt\n簽章 prompt 優先；否則取服務規則", small)
    _decision(draw, (1080, 405, 1500, 625), "個人化 prompt\n可用？", small)
    _process(draw, (1600, 440, 2020, 600), "建立 job\nstatus=queued，背景執行", small)
    _io(draw, (2110, 430, 2440, 600), "同步輸出：jobId\nresultToken、status", small)
    _io(draw, (1080, 710, 1500, 850), "否：503\n尚未送出圖片生成", small)

    _process(draw, (430, 900, 990, 1060), "背景呼叫 Replicate\n保留 renderPrompt", small)
    _decision(draw, (1080, 870, 1500, 1090), "供應商成功？", small)
    _database(draw, (1600, 885, 2020, 1080), "render_jobs\nGCS temporary／retained", small)
    _io(draw, (1080, 1120, 1500, 1260), "否：status=failed\nRENDER_PROVIDER_ERROR", small)

    _process(draw, (430, 1320, 990, 1475), "前端輪詢\nGET /render/jobs/{jobId}", small)
    _decision(draw, (1080, 1280, 1500, 1500), "completed？", small)
    _io(draw, (1600, 1310, 2020, 1485), "是：輸出 before／after\n/media/render/{jobId}", small)
    _terminator(draw, (2110, 1340, 2440, 1450), "結束／收藏／回饋", small)
    _io(draw, (1080, 1570, 1500, 1700), "否：等待後重試\n保留同一 jobId", small)

    # 正常路徑：輸入 → 驗證 → prompt → 建立工作 → 背景渲染 → 輪詢 → 輸出。
    for a, b in [((360, 205), (430, 205)), ((990, 205), (1080, 205)), ((1500, 205), (1600, 205)), ((1820, 310), (1820, 350)), ((1820, 350), (990, 350)), ((990, 350), (990, 430)), ((990, 515), (1080, 515)), ((1500, 515), (1600, 515)), ((2020, 515), (2110, 515)), ((1810, 600), (1810, 680)), ((1810, 680), (300, 680)), ((300, 680), (300, 900)), ((300, 900), (430, 900)), ((990, 980), (1080, 980)), ((1500, 980), (1600, 980)), ((710, 1060), (710, 1320)), ((990, 1397), (1080, 1397)), ((1500, 1397), (1600, 1397)), ((2020, 1397), (2110, 1397))]:
        _arrow(draw, a, b)
    # 失敗／等待分支。
    _arrow(draw, (2020, 205), (2110, 205))
    _arrow(draw, (1290, 625), (1290, 710))
    _arrow(draw, (1290, 1090), (1290, 1120))
    _arrow(draw, (1290, 1500), (1290, 1570))
    draw.text((1520, 205), "是", font=label, fill=(0, 0, 0))
    draw.text((2040, 180), "否", font=label, fill=(0, 0, 0))
    draw.text((1520, 485), "是", font=label, fill=(0, 0, 0))
    draw.text((1305, 650), "否", font=label, fill=(0, 0, 0))
    draw.text((1520, 950), "是", font=label, fill=(0, 0, 0))
    draw.text((1305, 1090), "否", font=label, fill=(0, 0, 0))
    draw.text((1520, 1340), "是", font=label, fill=(0, 0, 0))
    draw.text((1305, 1515), "否", font=label, fill=(0, 0, 0))
    image.save(FIGURES / "渲染端輸入輸出流程圖_黑白.png")


def prepare_algorithm_figures():
    """整理演算法端提供的兩張圖，移除原文件內嵌的舊圖號，交由本文統一編號。"""
    if Image is None or ImageDraw is None:
        raise RuntimeError("Bundled Python runtime 缺少 Pillow，無法整理演算法流程圖")
    for source, target, title, cover_height in [
        (ALGORITHM_FLOW_SOURCE, ALGORITHM_FLOW, "商品推薦系統整體流程", 92),
        (ALGORITHM_ACTIVITY_SOURCE, ALGORITHM_ACTIVITY, "個人化推薦演算法 UML 活動圖", 78),
    ]:
        if not source.exists():
            raise RuntimeError(f"找不到演算法端提供的流程圖：{source}")
        with Image.open(source) as original:
            image = original.convert("RGB")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, image.width, cover_height), fill=(255, 255, 255))
        font = _figure_font(45, bold=True)
        bbox = draw.textbbox((0, 0), title, font=font)
        x = (image.width - (bbox[2] - bbox[0])) // 2 - bbox[0]
        y = 18 - bbox[1]
        draw.text((x, y), title, font=font, fill=(0, 0, 0))
        image.save(target)


def add_figure(doc, image_path, caption, elements, width_cm=16.0):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run()
    run.add_picture(str(image_path), width=Cm(width_cm))
    elements.append(p._p)
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.paragraph_format.space_after = Pt(6)
    r = cap.add_run(caption)
    font_run(r, size=12, bold=True)
    elements.append(cap._p)


def replace_figure_image_before_caption(doc, caption_text, image_path, width_cm=16.0):
    """用使用者提供的圖片替換原文件中指定圖說前的圖片，保留原圖說位置。"""
    caption = find_paragraph(doc, lambda text: caption_text in text)
    if caption is None:
        raise RuntimeError(f"找不到要替換圖片的圖說：{caption_text}")

    # 原文件的圖片與圖說之間可能有空白段落，因此往前找到最近的圖片段落。
    previous = caption._p.getprevious()
    image_paragraph = None
    while previous is not None:
        if previous.tag == qn("w:p") and previous.findall(".//" + qn("w:drawing")):
            image_paragraph = previous
            break
        previous = previous.getprevious()
    if image_paragraph is None:
        raise RuntimeError(f"圖說前沒有可替換的圖片：{caption_text}")

    parent = image_paragraph.getparent()
    parent.remove(image_paragraph)

    replacement = doc.add_paragraph()
    replacement.alignment = WD_ALIGN_PARAGRAPH.CENTER
    replacement.paragraph_format.space_before = Pt(6)
    replacement.paragraph_format.space_after = Pt(2)
    replacement.add_run().add_picture(str(image_path), width=Cm(width_cm))
    caption._p.addprevious(replacement._p)


def classify_original(doc):
    top = re.compile(r"^(摘要|附錄[一二三四五六七八九十]|[壹貳參肆伍陸柒捌玖拾]+、)")
    mid = re.compile(r"^[一二三四五六七八九十]+、")
    # 只有「1.」「2.」等真正的小標題才套 Heading 3；避免把「5 月……」的正文誤判成標題。
    sub = re.compile(r"^\d+\.")
    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        if top.match(text):
            p.style = doc.styles["Heading 1"]
            p.paragraph_format.first_line_indent = Cm(0)
            for r in p.runs:
                font_run(r, size=14, bold=True)
        elif mid.match(text):
            p.style = doc.styles["Heading 2"]
            p.paragraph_format.first_line_indent = Cm(0)
            for r in p.runs:
                font_run(r, size=14, bold=True)
        elif sub.match(text):
            p.style = doc.styles["Heading 3"]
            p.paragraph_format.first_line_indent = Cm(0)
            for r in p.runs:
                font_run(r, size=14, bold=True)
        else:
            p.style = doc.styles["Normal"]
            p.paragraph_format.line_spacing = 1.0
            p.paragraph_format.first_line_indent = Cm(0.74)
            for r in p.runs:
                font_run(r, size=12)


def fix_known_typos(doc):
    """修正原始文件中已確認的技術名詞拼字與大小寫。"""
    replacements = (
        ("Decorate Me AI 個人化彩妝分析與推薦系統", "妝識你的美"),
        ("Decorate Me AI", "妝識你的美"),
        ("DecorateMe", "妝識你的美"),
        ("ollamma文字建議", "Ollama 文字建議"),
        ("ollamma", "Ollama"),
        ("api資安管理", "API 資安管理"),
        ("replicate api中chatgpt-image2", "Replicate API 中的 openai/gpt-image-2"),
        ("利用外接Replicate API 中的 openai/gpt-image-2模型", "利用外接的 Replicate API 中的 openai/gpt-image-2 模型"),
        ("1.臉部分析模組:", "1. 臉部分析模組："),
        ("2.API 資安管理:", "2. API 資安管理："),
        ("3.Ollama 文字建議:", "3. Ollama 文字建議："),
        ("4.爬蟲商品:", "4. 爬蟲商品："),
        ("5.演算法:", "5. 演算法："),
        ("6.多服務穩定性與部署:", "6. 多服務穩定性與部署："),
        ("一般使用者使用者案例圖", "一般使用者使用案例圖"),
    )
    for paragraph in doc.paragraphs:
        original = paragraph.text
        corrected = original
        for wrong, right in replacements:
            corrected = corrected.replace(wrong, right)
        if corrected != original:
            paragraph.text = corrected


def remove_unnecessary_blank_paragraphs(doc):
    """移除沒有文字、分頁、圖片或欄位的頂層空白段落，避免章節間出現錯誤留白。"""
    body = doc._element.body
    removed = 0
    protected_tags = {
        qn("w:br"),
        qn("w:drawing"),
        qn("w:pict"),
        qn("w:fldChar"),
        qn("w:instrText"),
    }
    for paragraph in list(body.findall(qn("w:p"))):
        visible_text = "".join(paragraph.itertext()).strip()
        if visible_text:
            continue
        if any(node.tag in protected_tags for node in paragraph.iter()):
            continue
        parent = paragraph.getparent()
        if parent is not None:
            parent.remove(paragraph)
            removed += 1
    return removed


def normalize_document_fonts(doc):
    """統一文件字型：中文標楷體，英文／數字 Times New Roman。"""
    def apply(paragraph, size=None):
        for run in paragraph.runs:
            set_run_font_family(run)
            if size is not None:
                run.font.size = Pt(size)

    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        style_name = paragraph.style.name if paragraph.style else ""
        is_heading = style_name.startswith("Heading ")
        is_caption = bool(re.match(r"^(圖|表)\s+\d+-\d+　", text)) and "\t" not in text
        is_index_line = text.endswith("\t—")
        is_cover = (
            text in {"專題系統文件書", "妝識你的美"}
            or text.startswith(("組別：", "指導老師：", "組員：", "日期："))
        )
        if is_heading:
            apply(paragraph, size=14)
        elif is_caption:
            apply(paragraph, size=12)
        elif is_index_line or is_cover:
            apply(paragraph)
        elif text:
            apply(paragraph, size=12)
        else:
            apply(paragraph)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    apply(paragraph, size=12)

    for section in doc.sections:
        for container in (section.header, section.footer):
            for paragraph in container.paragraphs:
                apply(paragraph)


def remove_shading_and_force_black(doc):
    containers = [doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                containers.append(cell.paragraphs)
                tc_pr = cell._tc.get_or_add_tcPr()
                for child in list(tc_pr):
                    if child.tag in {qn("w:shd"), qn("w:color")}:
                        tc_pr.remove(child)
    for paragraphs in containers:
        for p in paragraphs:
            for r in p.runs:
                r.font.color.rgb = RGBColor(0, 0, 0)
                rpr = r._element.get_or_add_rPr()
                color = rpr.find(qn("w:color"))
                if color is None:
                    color = OxmlElement("w:color")
                    rpr.append(color)
                color.set(qn("w:val"), "000000")
                color.attrib.pop(qn("w:themeColor"), None)

    # 初版文件的參考文獻有部分文字放在文字方塊中，python-docx 的
    # paragraphs API 讀不到這些內容；若只處理一般段落，Word 轉 PDF
    # 時仍會把原始超連結樣式顯示成藍字。這裡直接清理文件 XML 中
    # 所有文字執行屬性，保留網址文字但取消藍色、底線與 Hyperlink 樣式。
    xml_roots = [doc.element, doc.styles.element]
    for section in doc.sections:
        xml_roots.extend([section.header._element, section.footer._element])
    for root in xml_roots:
        for rpr in root.iter(qn("w:rPr")):
            rstyle = rpr.find(qn("w:rStyle"))
            if rstyle is not None and rstyle.get(qn("w:val")) in {"Hyperlink", "FollowedHyperlink"}:
                rpr.remove(rstyle)
            underline = rpr.find(qn("w:u"))
            if underline is not None:
                rpr.remove(underline)
            highlight = rpr.find(qn("w:highlight"))
            if highlight is not None:
                rpr.remove(highlight)
            shd = rpr.find(qn("w:shd"))
            if shd is not None:
                rpr.remove(shd)
            color = rpr.find(qn("w:color"))
            if color is None:
                color = OxmlElement("w:color")
                rpr.append(color)
            color.set(qn("w:val"), "000000")
            for attr in ("themeColor", "themeTint", "themeShade"):
                color.attrib.pop(qn(f"w:{attr}"), None)
        for shd in list(root.iter(qn("w:shd"))):
            parent = shd.getparent()
            if parent is not None:
                parent.remove(shd)


def grayscale_initial_reference_pages(doc):
    """把初版內嵌的參考文獻頁面轉成灰階，保留原文與網址但去除藍色。"""
    if Image is None or ImageOps is None:
        return 0
    converted = 0
    for part in doc.part.package.iter_parts():
        if type(part).__name__ != "ImagePart" or not hasattr(part, "blob"):
            continue
        try:
            image = Image.open(BytesIO(part.blob))
        except Exception:
            continue
        # 初版的參考文獻是 1192px 寬的截圖；其他系統畫面與流程圖不套用此處理。
        if image.size[0] != 1192 or image.size[1] not in {1061, 1684}:
            continue
        gray = ImageOps.grayscale(image.convert("RGB")).convert("RGB")
        payload = BytesIO()
        gray.save(payload, format="PNG")
        part._blob = payload.getvalue()
        converted += 1
    return converted


def insert_elements_before(target, elements):
    for element in elements:
        target._p.addprevious(element)


def find_paragraph(doc, predicate):
    return next((p for p in doc.paragraphs if predicate(p.text.strip())), None)


def compact_conclusion_spacing(doc):
    """只收斂結論區塊的段前段後，避免最後一行孤立成單獨一頁。"""
    rules = (
        ("陸、", 4, 2),
        ("一、\t總結", 2, 0),
        ("二、\t對未來", 2, 0),
        ("1.未來工作", 2, 0),
        ("2.未來商業模式", 2, 0),
        ("3.技術延伸方向", 2, 0),
    )
    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        for prefix, before, after in rules:
            if text.startswith(prefix):
                paragraph.paragraph_format.space_before = Pt(before)
                paragraph.paragraph_format.space_after = Pt(after)
                break


def chinese_number(number):
    """回傳報告小節使用的中文序號，支援本文件會用到的 1～99。"""
    digits = "零一二三四五六七八九"
    if number < 10:
        return digits[number]
    if number < 20:
        return "十" if number == 10 else "十" + digits[number - 10]
    tens, ones = divmod(number, 10)
    return digits[tens] + "十" + (digits[ones] if ones else "")


def next_subheading_number(doc, chapter_prefix, before_paragraph):
    """依原文件同一大章已有的 Heading 2 數量，計算下一個小節序號。"""
    paragraphs = doc.paragraphs
    chapter_index = next(
        (
            i
            for i, p in enumerate(paragraphs)
            if p.style.name == "Heading 1" and p.text.strip().startswith(chapter_prefix)
        ),
        None,
    )
    before_index = next((i for i, p in enumerate(paragraphs) if p._p is before_paragraph._p), len(paragraphs))
    if chapter_index is None:
        return 1
    pattern = re.compile(r"^[一二三四五六七八九十百]+、")
    count = sum(
        1
        for p in paragraphs[chapter_index + 1:before_index]
        if p.style.name == "Heading 2" and pattern.match(p.text.strip())
    )
    return count + 1


CHAPTER_DIGITS = {
    "壹": 1,
    "貳": 2,
    "參": 3,
    "肆": 4,
    "伍": 5,
    "陸": 6,
    "柒": 7,
    "捌": 8,
    "玖": 9,
    "拾": 10,
}


def chapter_number_from_text(text):
    match = re.match(r"^([壹貳參肆伍陸柒捌玖拾]+)、", text.strip())
    if not match:
        return None
    return CHAPTER_DIGITS.get(match.group(1))


def paragraph_text_from_element(element):
    return "".join(node.text or "" for node in element.iter(qn("w:t"))).strip()


def _caption_line_paragraph(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run(text)
    font_run(r, size=12, bold=True)
    return p


def add_caption_numbering(doc):
    """統一既有圖號，並為有內容的資料表補上章節式表號。"""
    body = doc._element.body
    figure_counters = {}
    table_counters = {}
    figure_entries = []
    table_entries = []
    caption_pattern = re.compile(r"圖\s*[0-9]+(?:\s*[-.:：]\s*[0-9]+)?\s*[.:：、]?")

    # 先處理原文件已有的圖說。即使原文寫成圖6、圖 6. 或一行兩個圖號，
    # 都改成同一章節下連號的「圖 3-1」格式，保留原本描述文字。
    current_chapter = 1
    for child in list(body.iterchildren()):
        if child.tag != qn("w:p"):
            if child.tag == qn("w:tbl"):
                continue
            continue
        text = paragraph_text_from_element(child)
        chapter = chapter_number_from_text(text)
        if chapter is not None:
            current_chapter = chapter
            continue
        if not text.startswith("圖") or not caption_pattern.search(text):
            continue
        counter = figure_counters.get(current_chapter, 0)
        matches = list(caption_pattern.finditer(text))
        parts = []
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            segment = text[match.start():end].strip()
            old_label = match.group(0)
            description = segment[len(old_label):].strip(" \t.:：、")
            counter += 1
            parts.append(f"圖 {current_chapter}-{counter}　{description}".rstrip())
        figure_counters[current_chapter] = counter

        # 清掉原段落的舊 runs 後寫回標準圖說，避免圖號留在不同 run 造成漏改。
        for child_node in list(child):
            if child_node.tag == qn("w:r"):
                child.remove(child_node)
        r = OxmlElement("w:r")
        rpr = OxmlElement("w:rPr")
        r.append(rpr)
        t = OxmlElement("w:t")
        t.set(qn("xml:space"), "preserve")
        t.text = parts[0]
        r.append(t)
        child.append(r)
        figure_entries.extend(parts)
        # 原文件有一段把兩個圖說寫在同一個段落；拆成獨立段落後，圖目錄才會一圖一行。
        previous = child
        for part in parts[1:]:
            extra = _caption_line_paragraph(doc, part)
            previous.addnext(extra._p)
            previous = extra._p

    # 為真正有文字的表格加上表說；空白表格多半是原文件的版面容器，不列入表目錄。
    current_chapter = 1
    for child in list(body.iterchildren()):
        if child.tag == qn("w:p"):
            text = paragraph_text_from_element(child)
            chapter = chapter_number_from_text(text)
            if chapter is not None:
                current_chapter = chapter
            continue
        if child.tag != qn("w:tbl"):
            continue
        table_text = " ".join(node.text or "" for node in child.iter(qn("w:t"))).strip()
        if not table_text:
            continue
        following = child.getnext()
        following_text = paragraph_text_from_element(following) if following is not None and following.tag == qn("w:p") else ""
        if following_text.startswith("表 "):
            table_entries.append(following_text)
            continue
        counter = table_counters.get(current_chapter, 0) + 1
        table_counters[current_chapter] = counter
        rows = child.findall(qn("w:tr"))
        first_cells = rows[0].findall(qn("w:tc")) if rows else []
        first_row = [paragraph_text_from_element(cell) for cell in first_cells]
        header_key = first_row[0] if first_row else ""
        title_map = {
            "技術／方法": "技術與方法比較",
            "模型階段": "模型階段與選擇演進",
            "工具／技術": "開發工具與選用理由",
            "主要模組／檔案": "系統模組與檔案",
            "層次": "前端與 Gateway 責任邊界",
            "階段": "渲染端輸入與輸出",
            "狀態": "模型回饋與部署狀態",
            "名稱": "系統功能",
            "分析部位": "模型五折實驗結果",
            "部位": "使用者回饋統計",
            "比較項目": "前端、後台與技術比較",
            "日期": "臉部模型訓練工作流",
            "方法／條件": "模型訓練方法比較",
            "發現問題": "UAT 測試工作流",
            "成果": "模型成果檔案與部署驗證",
            "端別": "跨端資料補件清單",
            "處理項目": "前端照片前處理與資料",
            "工作類型／集合": "Worker 狀態機與工作留",
            "工作面向": "Worker 升版判定與執行細節",
            "項目": "Worker 未完成事項與阻塞原因",
            "測試檔／情境": "Worker 測試涵蓋與限制",
            "資料來源類型": "出版與原始資料來源",
            "服務／模型": "Ollama 服務與模型設定",
            "輸入資料": "Ollama 輸入資料",
            "輸出區塊": "Ollama 輸出欄位",
            "組合順序": "Ollama 回應驗證與渲染提示組合",
            "Ollama 項目": "Ollama 安全邊界與目前驗證界線",
            "推薦入口": "商品推薦入口與個人化邊界",
            "資料區段": "商品推薦資料欄位",
            "商品類別": "商品推薦計分權重",
            "前端畫面／元件": "商品推薦 API 與前端呈現",
            "回傳欄位": "商品推薦回傳欄位",
            "困難": "演算法端新增內容的困難與處理",
        }
        title = title_map.get(header_key, "資料整理表")
        caption = f"表 {current_chapter}-{counter}　{title}"
        p = _caption_line_paragraph(doc, caption)
        # 表說和圖說採同一規則：表格在前，表號與解釋放在表格下方。
        child.addnext(p._p)
        table_entries.append(caption)

    return figure_entries, table_entries


def build_cover_and_static_toc(doc, figure_entries=None, table_entries=None):
    first = doc.paragraphs[0]
    elements = []

    for text, size, before, after in [
        ("專題系統文件書", 24, 50, 20),
        ("妝識你的美", 24, 0, 38),
        ("組別：＿＿＿＿＿＿＿＿＿＿＿＿", 13, 0, 10),
        ("指導老師：＿＿＿＿＿＿＿＿老師", 13, 0, 10),
        ("成員：＿＿＿＿＿＿＿＿＿＿＿＿", 13, 0, 10),
        ("學年度：＿＿＿＿學年度", 13, 0, 45),
    ]:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(before)
        p.paragraph_format.space_after = Pt(after)
        r = p.add_run(text)
        font_run(r, size=size, bold=size >= 21)
        elements.append(p._p)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("（組別、老師與成員請依實際資料填寫）")
    font_run(r, size=10)
    elements.append(p._p)
    new_page_break(doc, elements)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(14)
    r = p.add_run("目錄")
    font_run(r, size=18, bold=True)
    elements.append(p._p)
    toc_entries = [
        ("摘要", 1),
        ("壹、緒論", 1),
        ("一、背景介紹", 2),
        ("二、專題的目的及重要性", 2),
        ("三、主要研究問題或目標", 2),
        ("四、系統功能簡介", 2),
        ("五、系統使用對象", 2),
        ("六、系統特色", 2),
        ("貳、相關技術應用與重要文獻", 1),
        ("一、相關研究或技術", 2),
        ("二、研究優缺點", 2),
        ("三、臉部分析模型的選擇與演進", 2),
        ("參、系統概要設計", 1),
        ("一、系統架構", 2),
        ("二、系統流程", 2),
        ("三、資料與模型分析流程", 2),
        ("四、會員與權限", 2),
        ("五、回饋與送訓", 2),
        ("六、模型分析與使用者回饋資料流程", 2),
        ("（一）前端照片前處理與提亮功能的技術界線", 3),
        ("（二）前端與 Gateway 的實際責任邊界", 3),
        ("（三）目前程式與測試中已存在的資料範例", 3),
        ("（四）渲染端的輸入與輸出", 3),
        ("（五）Ollama 個人化妝容建議模組", 3),
        ("（六）商品推薦演算法與排序流程", 3),
        ("（七）演算法端新增內容的困難與驗證", 3),
        ("肆、系統開發工具與使用環境", 1),
        ("伍、系統實作及實驗結果", 1),
        ("一、系統功能詳細描述", 2),
        ("二、實驗數據", 2),
        ("三、實作成果評估", 2),
        ("四、技術比較", 2),
        ("五、遭遇的問題和挑戰", 2),
        ("六、臉部分析模型訓練工作流", 2),
        ("七、模型訓練方法與實驗結果", 2),
        ("八、UAT 測試工作流", 2),
        ("九、模型成果檔案與部署驗證", 2),
        ("十、Worker 技術細節與完成界線", 2),
        ("十一、出版與原始資料來源", 2),
        ("陸、結論及未來發展", 1),
        ("一、總結主要貢獻", 2),
        ("二、未來研究或發展建議", 2),
    ]
    for label, level in toc_entries:
        add_toc_line(doc, label, level, elements)
    new_page_break(doc, elements)

    # 範本的目錄之後另外整理圖目錄、表目錄；頁碼先保留同一個右側欄位，
    # 待正文內容定稿後即可統一更新，不把圖表名稱塞回正文目錄同一行。
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(14)
    r = p.add_run("圖目錄")
    font_run(r, size=18, bold=True)
    elements.append(p._p)
    for caption in figure_entries or []:
        add_toc_line(doc, caption, 2, elements)
    new_page_break(doc, elements)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(14)
    r = p.add_run("表目錄")
    font_run(r, size=18, bold=True)
    elements.append(p._p)
    for caption in table_entries or []:
        add_toc_line(doc, caption, 2, elements)
    new_page_break(doc, elements)
    insert_elements_before(first, elements)


def add_model_history_under_related_tech(doc):
    target = find_paragraph(doc, lambda t: t.startswith("參、") and "系統概要設計" in t)
    elements = []
    new_heading(doc, "三、臉部分析模型的選擇與演進", elements, 2)
    new_body(doc, "我在模型開發上不是一開始就直接選 ConvNeXt。前期先用 MediaPipe Face Mesh 和幾何比例建立規則式基線，再用整張臉 CNN，之後才改成依五官區域裁切 ROI 的 CNN。當我發現隨機切分會造成身份洩漏、重複圖片會讓驗證分數失真後，才把 identity split、五折交叉驗證、固定 holdout 和資料去重列為正式流程。", elements)
    new_body(doc, "這段歷程的重點不是模型越大越好，而是每換一種方法，我都要回答上一版遇到的問題。規則式的問題是閾值會讓某些類別永遠不出現；整臉 CNN 的問題是小部位比例太小且容易學到背景；MobileNet 的問題是小資料下部分部位仍不穩；DINOv2 的問題是部署成本與跨部位穩定性；最後 ConvNeXt-Tiny 是在相同資料切分與訓練條件下，整體較平衡的選擇。", elements)
    table = new_table(doc, ["模型階段", "實際做法", "當時結果與問題", "後續決定"], [
        ["規則式基線", "landmark 比例、幾何特徵、if-else／決策樹", "眉型幾乎全判彎月眉、眼型高度集中、鼻型幾乎全判標準鼻；部分閾值是死碼。", "保留作 fallback、診斷與解釋，不作主要答案。"],
        ["整張臉 CNN", "160×160 整臉輸入", "鼻子、眉毛在影像中太小；模型可能學背景、髮型或個人身份。", "改成五官各自裁 ROI。"],
        ["ROI MobileNetV3", "ImageNet 預訓練、每部位獨立分類器", "按人切分約 0.38～0.67，方向正確但資料與類別仍不穩。", "作基準線，開始公平比較。"],
        ["DINOv2", "凍結 ViT-S/14 embedding＋LogReg／SVM", "眼型一度較 CNN 好，但檔案大、線性 head 有版本相容性與類別同步問題。", "保留實驗／shadow，不直接當正式 runtime。"],
        ["ConvNeXt-Tiny", "ROI、identity split、5-fold、ONNX", "在同一 protocol 下對眼型、鼻型、唇型與整體較平衡，但檔案較大、推論成本較高。", "作 BASIC／PRO 主要架構，搭配 manifest 與 promotion。"],
    ], [3.2, 5.1, 7.3, 5.0], 8.8)
    elements.append(table._tbl)
    new_body(doc, "目前 BASIC 的任務是臉型、眉型、眼型、鼻型、唇型五個獨立分類；PRO 側面鼻型則是另一個整張側臉影像任務。眉型歷史上曾使用三類，現行類別檔是四類；眼型曾經合併不同類別；鼻型把窄鼻併入標準鼻；唇型把 M 型唇併入花瓣唇。這些類別變更會改變題目難度，所以不同版本的分數不能直接相減。", elements)
    insert_elements_before(target, elements)


def add_system_data_flow_under_design(doc):
    target = find_paragraph(doc, lambda t: t.startswith("肆、") and "系統開發工具" in t)
    elements = []
    # 參章原有一至五節，這段整合資料沿用初版格式接在其後，固定為「六」。
    section_number = "六"
    new_heading(doc, f"{section_number}、模型分析與使用者回饋資料流程", elements, 2)
    new_body(doc, "系統使用者上傳照片後，先由前端把需求送到 Gateway。因為前端和 Gateway 是我這邊掌握最完整的部分，所以這一段記錄得最細：前端負責畫面狀態、欄位組裝、輪詢和錯誤呈現；Gateway 負責登入身分、訪客額度、路由白名單、上游服務驗證、錯誤語意轉換、私人媒體路徑和 job 串接。經過 Gateway 後，才由 Face Mesh 取得臉部關鍵點，再依部位裁出 ROI，交給對應模型產生臉型、眉型、眼型、鼻型與唇型結果。", elements)
    new_code = doc.add_paragraph()
    new_code.paragraph_format.left_indent = Cm(0.8)
    new_code.paragraph_format.line_spacing = 1.0
    r = new_code.add_run("上傳照片 → Face Mesh → ROI → 五官模型 → analysisPackage → 建議／渲染／推薦 → 使用者確認或修正")
    font_run(r, size=10, name="Consolas")
    elements.append(new_code._p)

    new_heading(doc, "（一）前端照片前處理與提亮功能的技術界線", elements, 3)
    new_body(doc, "臉部分析前端在送出照片前，會先處理檔案格式、讀取影像尺寸與必要的圖片打包資料。BASIC 使用正面照片，PRO 則可分別傳送 front、left45、right45 與 side。這裡的影像處理要和模型訓練的 augmentation 分開：前端處理的是使用者這一次上傳的檔案，訓練 augmentation 則是訓練期間對資料做的變化，不能把兩者寫成同一個步驟。", elements)
    frontend_image_table = new_table(doc, ["處理項目", "目前核對到的技術與資料", "送往哪裡／判讀方式", "目前判定"], [
        ["照片來源", "使用者選取的 image File 或相機擷取後的 Blob；BASIC 欄位為 file，PRO 欄位為 front、left45、right45、side。", "以 FormData 送至 face Basic／Pro 分析路由；PRO 的側面照片是選填，正面照片是必要輸入。", "已在前端 API 程式中看到"],
        ["影像解碼與尺寸", "使用 createImageBitmap(file) 讀取 originalWidth、originalHeight；Worker 完成後呼叫 bitmap.close()。", "尺寸資料寫入 imageMeta，用於追蹤原始照片，不等於模型分類結果。", "已在 image-worker.js 中看到"],
        ["Worker 圖片打包", "使用 OffscreenCanvas drawImage；storageMaxEdge=1024、storageJpegQuality=0.78；輸出 image/jpeg 的 blob 與 dataUrl。", "主要給 analysisPackage 後續建議／渲染使用；meta 會記錄 compressedWidth、compressedHeight、compressedSize、compressionRatio 與 processedBy。", "已在 image-worker.js／api.js 中看到"],
        ["主執行緒備援", "瀏覽器不支援 Worker、OffscreenCanvas 或 createImageBitmap，或 Worker 發生錯誤／逾時時，改用 document.createElement('canvas')、drawImage 與 canvas.toBlob。Worker timeout 為 30000 ms。", "備援輸出仍是 JPEG File 與 dataUrl，processedBy 會標記 main-thread。", "已在 api.js 中看到"],
        ["臉部分析送出檔案", "analyzeFace 與 analyzeFacePro 直接把 file／各角度 files 放入 FormData；ImagePipeline.metaFromFile 另外產生 role、originalName、originalType、originalSize、width 與 height。", "分析 API 收到的是檔案與欄位；imageMeta 是前端紀錄資料，不能直接當成後端已保存的影像。", "已在 api.js 中看到"],
        ["照片提亮", "本次核對的 image-worker.js 與 api.js 只有解碼、縮放、JPEG 壓縮與 Worker 備援，沒有看到 ctx.filter='brightness(...)'、像素逐點加亮或其他會改變上傳照片亮度的程式。CSS 中的 filter:brightness 是介面視覺效果，不能代表照片已被提亮。", "若另一個前端版本確實有照片提亮，必須補上該版本檔案或 commit；目前文件不能把它寫成已驗證功能。", "NOT VERIFIED"],
    ], [3.0, 7.0, 5.0, 2.6], 8.4)
    elements.append(frontend_image_table._tbl)
    new_body(doc, "因此本系統目前可以明確說明的前端影像技術是『檔案檢查、影像解碼、尺寸縮放、JPEG 壓縮、data URL 產生、Worker 執行與主執行緒備援』。如果使用者介面上看到照片變亮，還要確認那是預覽 CSS 效果、相機自動曝光，還是實際送往 Face Basic／Face Pro 前的像素處理；三者的資料位置不同，不能只看畫面顏色判定。", elements)

    new_heading(doc, "（二）前端與 Gateway 的實際責任邊界", elements, 3)
    new_body(doc, "前端不是直接把公開金鑰交給每一個內部服務，而是把操作送到我們的 Gateway。Gateway 先取得目前使用者或訪客的 actor 身分，再依路徑和 HTTP method 判斷是否允許，之後才用服務端認得的 API key 或內部標頭呼叫臉部、建議、渲染、會員與商品服務。這樣前端只需要知道穩定的 Gateway 路徑，不必知道各服務的內部 URL、GCS 原始網址或上游供應商細節。", elements)
    gateway_table = new_table(doc, ["層次", "我這邊實際處理的內容", "送出／回傳的關鍵資料"], [
        ["前端輸入", "照片、妝容風格、strength、分析結果包、faceJobId；畫面保存 loading、queued、running、completed、failed。", "image data URL、styleId、strength、analysisPackage、faceJobId。"],
        ["Gateway 驗證", "登入 session／訪客 session、actorId、quota、CSRF、method 與 route allowlist；不讓前端自訂任意上游路徑。", "X-User-ID、服務端 API key、允許的內部 path。"],
        ["Gateway 串接", "把同一筆 faceJobId、render jobId、feedbackId 串起來，並保留可追查的錯誤碼；渲染結果改寫成穩定的 Gateway media path。", "jobId、resultToken、analysisPackage、renderPrompt、ownerId。"],
        ["前端輸出", "先接非同步 job 回應，再輪詢結果；成功才顯示妝前／妝後圖、建議與收藏，失敗顯示可理解的原因與是否可重試。", "status、afterImageUrl、beforeImageUrl、error.code、retryable。"],
        ["安全邊界", "前端不能用自由文字 prompt 繞過規則；原始 GCS 直連網址不能直接暴露；別人的 job、media 與管理員資料必須被 owner／admin 擋下。", "/media/render/{jobId}、/media/render/{jobId}/before、audit log。"],
    ], [2.6, 8.2, 5.2], 8.2)
    elements.append(gateway_table._tbl)

    new_heading(doc, "（三）目前程式與測試中已存在的資料範例", elements, 3)
    new_body(doc, "下面這些不是我另外編的示意值，而是目前專案程式、測試 fixture、模型 manifest 與 promotion ledger 裡已經存在的資料。我把會在每次執行時變動的 token、時間和雜湊識別碼標成動態欄位；文件中的固定值則可以直接回到來源檔案核對。這樣在口試時，我可以說明 Gateway 實際收到什麼、臉部服務建立什麼，以及模型版本如何留下證據。", elements)
    actual_gateway_table = new_table(doc, ["資料位置／端點", "目前實際存在的值", "在流程中的用途"], [
        ["Gateway 臉部 BASIC 路由", "POST /v1/face/pose；POST /v1/face/analyze/basic；POST /v1/face/jobs/basic；GET /v1/face/jobs/{jobId}；GET /v1/face/jobs/{jobId}/result；POST /v1/face/jobs/{jobId}/feedback", "前端只能透過 Gateway 使用白名單路徑，不能自行指定任意上游 URL。"],
        ["BASIC 建立 job 的初始資料", "jobId=JOB-012345abcdef（測試中存在的 fixture）；status=queued；progress=0；stage=upload；analysisPackageId=null；resultToken 為執行時產生的 32 位十六進位字串。", "前端收到的是非同步工作，不可以把 queued 直接當成分析完成。"],
        ["Gateway public-config", "apiMode=gateway；memberDatabaseUrl=/member-database；productUrl=/product-api；crawlerUrl=/admin-api；guestTrialMaxRuns 預設為 3。", "前端取得穩定的 Gateway 路徑，不暴露會員、商品、爬蟲服務的內部網址。"],
        ["回饋 fixture", "feedbackId=FB-JOB-1；jobId=JOB-1；predicted={眉型：落尾眉，眼型：圓眼}；corrections={眉型：一字眉}；contributed=true。", "這筆資料示範使用者修正如何和原本預測、jobId 以及是否貢獻樣本串在一起。"],
        ["Gateway 媒體路徑", "輸入 jobId=0123456789abcdef0123456789abcdef 時，afterImageUrl 會改寫成 /media/render/{jobId}；beforeImageUrl 會改寫成 /media/render/{jobId}/before。", "瀏覽器不會拿到 storage.googleapis.com 或 replicateTempUrl，讀圖仍要經過 owner 檢查。"],
        ["可追查的錯誤資料", "GUEST_TRIAL_EXHAUSTED；MEMBER_AUTH_REQUIRED；PACKAGE_BUILD_FAILED；RENDER_PROVIDER_ERROR。", "Gateway 或上游服務把錯誤轉成前端看得懂的 code，前端再決定顯示原因、是否可重試。"],
    ], [3.1, 8.0, 5.0], 8.7)
    elements.append(actual_gateway_table._tbl)
    new_body(doc, "這張表的資料來源是 `gateway/ai_gateway.py`、`face/Face_analyzer_BASIC.py`、`tests/ai_gateway_test.py` 與 `face/face_feedback.py`。其中 `JOB-012345abcdef` 和 `FB-JOB-1` 是測試中真的拿來驗證權限、回饋與訪客額度的 fixture；它們不是宣稱目前線上資料庫一定還留著的 production job。", elements)

    actual_model_table = new_table(doc, ["臉部模型／資料項目", "目前實際存在的值", "驗證方式"], [
        ["analysisPackage 契約", "schemaVersion=2026-08-v2；mode=BASIC；client=web；status=completed；faceAnalysis 包含 faceShape、browShape、eyeShape、noseFront、lipShape；generativeText.provider=ollama；render.provider=replicate。", "直接對照 face/analysis_package.py：契約欄位見 reference_build_analysis_package()（參考實作，無呼叫端），線上正規化見 normalize_face_analysis()。"],
        ["BASIC job 儲存與生命週期", "collection=face_jobs_basic；timeoutSeconds=180；retentionSeconds=3600；maxCount=200；job 狀態包含 queued、processing、completed、failed。", "直接對照 face/Face_analyzer_BASIC.py 的常數、job_data 與 /health 回應。"],
        ["現行五官分類表", "臉型：鵝蛋臉、圓形臉、方形臉、長形臉、心形臉；眉型：一字眉、彎月眉、挑眉、落尾眉；眼型：桃杏眼、圓眼、鳳眼、下垂眼；鼻型：標準鼻、寬鼻；唇型：厚唇、薄唇、微笑唇、花瓣唇。", "對照 face/analysis_package.py 與 models/basic_features_roi/*_classes.json；模型輸出再轉成對應 code。"],
        ["最近模型 promotion 紀錄", "runId=TR-0f4d71078deb5828；version=20260904_brow_nose；at=2026-09-04T00:42:26；眉型 newMacro=0.531836；鼻型 newMacro=0.902661。", "對照 models/promotion_ledger.json；這是已寫入 ledger 的部署紀錄，不把它誇大成所有部位都重新換模。"],
        ["模型 manifest 與檔案證據", "manifest version=20260904_brow_nose；gcsPrefix=gs://decorate-me-models/20260904_brow_nose；清單共 7 個檔案；face_shape.onnx=111,380,415 bytes；brow_shape.onnx=111,377,337 bytes；nose_shape.onnx=111,371,185 bytes。", "對照 tools/face_models_manifest.json，並以本機檔案大小與 SHA-256 逐一比對；目前清單內 7 個檔案皆存在且雜湊相符。"],
    ], [3.1, 8.0, 5.0], 8.7)
    elements.append(actual_model_table._tbl)
    new_body(doc, "我在這裡特別把「程式契約」、「測試資料」、「模型檔案」和「部署 ledger」分開，因為它們代表的證據層級不同：測試 fixture 可以證明流程和權限規則，manifest 可以證明檔案版本與完整性，promotion ledger 才能證明哪一次模型 promotion 被記錄；三者不能混在一起說成同一筆線上使用者資料。", elements)

    new_heading(doc, "（四）渲染端的輸入與輸出", elements, 3)
    new_body(doc, "渲染端不是只收到一張照片。正式請求以 `POST /render/jobs` 的非同步方式處理，輸入至少包含 image、styleId、strength，並可帶 analysisPackage、faceJobId，以及由建議服務簽出的 renderPromptEn、promptSignature 和 promptSignatureVersion。渲染端先驗證圖片格式、大小與 style，再決定採用已簽 prompt 或安全的風格規則；建立 job 後立即回傳識別資料，背景工作才呼叫 Replicate，完成後把妝前／妝後圖和 renderPrompt 寫回工作紀錄。", elements)
    render_table = new_table(doc, ["階段", "渲染端收到／產生的資料", "前端或後台要怎麼判讀"], [
        ["輸入", "image=data:image/...; styleId；strength；analysisPackage；faceJobId；可選的已簽 renderPromptEn。", "這些欄位屬於同一次渲染，不能只把 image 當成完整上下文。"],
        ["同步建立工作", "status=queued、jobId、resultToken、renderPrompt、faceJobId、ownerId。", "前端先保存 jobId 和 token，不把 queued 當成完成。"],
        ["背景完成", "status=completed、afterImageUrl、beforeImageUrl、replicateTempUrl、model、renderPrompt。", "after 和 before 都要存在才算完整的收藏對比；缺 before 要標示降級。"],
        ["渲染失敗", "status=failed、error.code=RENDER_PROVIDER_ERROR 或上游／prompt／圖片驗證錯誤。", "retryable 決定能否重試；不可以顯示上一筆或固定假結果。"],
        ["對外媒體輸出", "Gateway 改寫成 `/media/render/{jobId}` 和 `/media/render/{jobId}/before`，短效簽章與 owner 檢查在讀取時處理。", "前端只使用 Gateway media path，不直接使用 GCS temporary／retained URL。"],
    ], [2.6, 8.2, 5.2], 8.2)
    elements.append(render_table._tbl)
    add_figure(doc, USER_GATEWAY_SWIMLANE, "圖 3-1　前端與 Gateway 及後端服務的橫向泳道資料流程圖", elements, 16.0)
    add_figure(doc, FIGURES / "渲染端輸入輸出流程圖_黑白.png", "圖 3-2　渲染端從輸入驗證、建立非同步 job 到 before／after 輸出的流程", elements, 16.0)

    new_body(doc, "使用者修正結果後，如果明確同意提供影像，系統才會把回饋標籤與符合條件的影像分別保存到 Firestore 與 GCS。管理員在後台看樣本、採用或修改標籤後，才建立 training run；地端 worker 下載已審核樣本，合併既有資料後重新訓練。這表示「畫面上的修正」、「已保存回饋」、「已送訓」、「訓練完成」和「模型已上線」是五個不同狀態。", elements)
    table = new_table(doc, ["狀態", "系統要留下的證據", "不能誤解成"], [
        ["使用者修正", "predicted、corrections、jobId、feedbackId", "模型已經改權重"],
        ["影像貢獻成功", "明確同意、實際 GCS 物件、metadata、contributed=true", "只要 API 回 204 就一定有圖"],
        ["管理員採用", "reviewDecisions、reviewLabels、reviewedAt", "使用者標籤直接是真實 ground truth"],
        ["送訓排隊", "runId、feedbackIds、selections、sampleCount", "worker 已開始訓練"],
        ["訓練完成", "metrics、ONNX、classes、summary、before／after", "線上服務已換模"],
        ["promotion 完成", "manifest、hash、revision、health／smoke、rollback", "只有本地檔案變新"],
    ], [3.8, 10.0, 6.8], 8.8)
    elements.append(table._tbl)
    new_heading(doc, "（五）Ollama 個人化妝容建議模組", elements, 3)
    new_body(doc, "Ollama 在本系統中不是拿來重新判斷使用者臉型的工具，而是位於臉部分析與圖片渲染之間的個人化建議層。臉型、眉型、眼型、鼻型、唇型與四季型先由前段臉部分析模組產生結構化資料；Ollama 再由 Gemma3 將這些資料、使用者選擇的妝容風格與 userNote 整理成可顯示的文字建議。正面照片存在時，LLaVA 可補充皮膚質感、膚色視覺狀態與整體平衡，但不能覆蓋原本的結構化五官分類。", elements)
    new_body(doc, "所以本系統的實際方向不是『照片直接交給 LLM，讓模型自己猜臉型並生圖』，而是『電腦視覺分析、結構化特徵、固定妝容規則與 LLM 文字個人化』一起工作。文字建議和圖片渲染使用的 renderPromptEn 也分開處理：Gemma3 負責自然語言，Python 後端的規則組合器負責把身份保留、妝容風格、可見度與強度限制組成渲染提示。", elements)
    ollama_port_table = new_table(doc, ["服務／模型", "目前文件記載的設定", "在本系統中的責任"], [
        ["Ollama 原生 API", "http://127.0.0.1:11434；原生路徑包含 /api/generate 與 /api/tags。", "實際執行 Gemma3 與 LLaVA；不直接暴露給瀏覽器。"],
        ["Ollama Suggestion Service", "FastAPI／Uvicorn，http://127.0.0.1:8010；提供 POST /suggest 與 GET /health。", "把本系統的輸入契約、驗證、Fallback 與 Prompt Builder 包起來，讓前端與 Gateway 不必知道原生 API 細節。"],
        ["Gemma3", "文字模型預設為 gemma3；呼叫時記載 format=json、stream=false、num_predict=4096、temperature=0.35、top_p=0.85。", "產生 overall、六個 parts 與 personalization 等個人化妝容文字建議。"],
        ["LLaVA", "視覺補充模型預設為 llava:latest；有正面照片時才使用。", "輸出 100 字以下英文 vision_feedback，作為 Gemma3 與 Render Prompt Builder 的補充上下文。"],
    ], [3.5, 7.0, 6.0], 8.2)
    elements.append(ollama_port_table._tbl)
    new_body(doc, "目前要把兩個 Port 分開講清楚：11434 是 Ollama 原生推論服務，8010 是我們另外建立的 Suggestion Service。開發測試期間可透過 Cloudflare Quick Tunnel 把本機 127.0.0.1:8010 暫時提供給雲端 Gateway，但這只是一條連線通道，不能寫成 Ollama 部署在 Cloudflare，也不能把 Quick Tunnel 當成正式 production 架構。", elements)

    ollama_input_table = new_table(doc, ["輸入資料", "來源", "用途與限制"], [
        ["faceAnalysis／analysisPackage", "前段 Face Mesh、ROI 與五官分類結果。", "提供 faceShape、browShape、eyeShape、noseShape、lipShape、season 等結構化特徵；不是 Gemma3 自己看照片猜出的分類。"],
        ["style", "使用者從前端選取的妝容風格。", "決定文字建議、固定 Style DNA、妝容可見度與強度規則。"],
        ["userNote", "使用者在前端輸入的偏好或限制。", "補充個人需求，不取代結構化五官資料和固定 Style 規則。"],
        ["analysisPackage.images.front.compressedDataUrl", "前端壓縮後的正面照片；有提供時才送 LLaVA。", "作為視覺補充，不是必要輸入；缺少圖片時改用結構化參數。"],
    ], [4.5, 6.0, 6.0], 8.2)
    elements.append(ollama_input_table._tbl)
    new_body(doc, "Suggestion Service 的輸出要先經過 JSON parse、欄位檢查與 Server Validation，不能把模型回傳的自然語言直接當成前端固定欄位。後端會用這一次真正收到的 structured features 覆蓋 personalization.sourceFeatures，避免模型改寫分類名稱、漏掉欄位或自行補出不存在的特徵。", elements)
    ollama_output_table = new_table(doc, ["輸出區塊", "目前資料內容", "使用位置"], [
        ["overall", "整體妝容摘要。", "前端快速顯示這次推薦的整體方向。"],
        ["parts", "base、eyebrow、eyes、contour、cheeks、lips 六個部位；各部位至少有 analysis、steps、avoid。", "前端顯示可執行的化妝步驟與避免事項。"],
        ["personalization", "title、profileSummary、sourceFeatures、featureAdjustments、combinationNote、styleConnection、personalizedStory。", "說明哪個特徵影響哪個妝容決策，讓推薦可追溯。"],
        ["renderPromptEn／fluxPromptEn", "由 Python Rule Builder 組合的英文渲染提示；目前文件記載兩者保持相同以維持相容。", "交給圖片渲染服務；不是把 Gemma3 的自然語言整段直接當成唯一 Prompt。"],
        ["promptSignature", "有設定 Signing Secret 時供後續驗簽。", "讓渲染端判斷提示是否由受信任的建議服務產生；正式簽章契約仍須依實際端點核對。"],
    ], [4.0, 8.0, 4.5], 8.0)
    elements.append(ollama_output_table._tbl)

    new_heading(doc, "Ollama 回應驗證與渲染提示組合", elements, 3)
    new_body(doc, "Gemma3 呼叫時會要求 format=json、stream=false，讓服務可以等待完整結果後執行 json.loads()。如果回傳仍包含 Markdown code fence，後端先移除標記再解析；如果缺少 overall 或 parts 的必要部位，才套用預設 fallback。這裡的 fallback 是為了避免前端因欄位缺失而崩潰，不代表模型一定產生了正確內容，也不代表正式 200 組 request／response 已經完成驗收。", elements)
    new_body(doc, "目前補件文件記載的結構化方式，是以 JSON 欄位和受控詞彙保存 preferredColors、finishTags、avoidColors 與 avoidTags；同時保留自然語言 summary 作畫面顯示。Ollama 文件也明確指出，format=json 不等於完整 Business Schema Validation，後續仍可再加更嚴格的 JSON Schema。這一點要和已存在的 parse／欄位補齊分開描述。", elements)
    prompt_table = new_table(doc, ["組合順序", "由誰處理", "作用"], [
        ["1. Identity Preservation", "Python Rule Builder", "保留人物身份、五官與臉型的限制。"],
        ["2. Skin Retouching", "Python Rule Builder", "限制皮膚修飾範圍，避免把修圖寫成換臉。"],
        ["3. Personalized Face Adaptation", "Python Rule Builder＋實際 features", "把臉部分析結果轉成個人化妝容調整。"],
        ["4. Selected Style＋Fixed Style DNA", "服務端固定規則", "維持不同妝容風格的必要元素與差異。"],
        ["5. Style Visibility／Intensity Controls", "服務端固定規則", "強度 4／5、5／5 的元素必須清楚可見；0／5 的排除元素必須避免。"],
        ["6. Final Makeup Enforcement", "Python Rule Builder", "在交給渲染服務前再次補足必要妝容條件。"],
    ], [5.0, 5.0, 6.5], 8.0)
    elements.append(prompt_table._tbl)
    new_body(doc, "以新版日雜清透妝為例，補件文件記載 Style DNA 為『JAPANESE AIRY PLAYFUL IGARI MAKEUP』，並將『BLUSH — PRIMARY FEATURE』設為主要特徵，同時排除 Korean mocha eye makeup、strong aegyo-sal、Korean glass skin 與 structured lash clusters。這些規則是用來控制 Style 差異，不是由單次 Gemma3 文字自由決定。", elements)
    new_body(doc, "LLaVA 的 vision_feedback 只能作額外觀察，因為照片會受光線、白平衡、遮擋、解析度與壓縮影響。正式五官分類仍以結構化分析為優先；而 identity lock 關閉後的實際妝前／妝後輸出比對目前仍是 NOT VERIFIED，不能用 Prompt 中有 Identity Preservation 就宣稱圖片一定保留本人特徵。", elements)

    new_heading(doc, "Ollama 的安全邊界與目前驗證界線", elements, 3)
    ollama_security_table = new_table(doc, ["Ollama 項目", "目前記載的作法", "完成界線"], [
        ["前端呼叫位置", "Browser／Gateway 呼叫 FastAPI :8010，不直接呼叫 Ollama :11434。", "正式 200 組 request／response、認證轉送與完整錯誤碼仍需由 Ollama 端補資料；目前不能寫成已完成端到端驗收。"],
        ["API Key", "Suggestion Service 以 X-API-Key 與 hmac.compare_digest() 做基本驗證；正式環境應放環境變數。", "不能把文件中的設定範例當成實際秘密值，也不能把 health response 當成完整權限驗證。"],
        ["Health check", "GET /health 再查 Ollama /api/tags，用來區分 FastAPI 存活與 Ollama 可連線。", "health 200 只能證明服務回應，不等於正式模型版本、輸出內容或 E2E 已驗證。"],
        ["Cloudflare Quick Tunnel", "開發測試期間將本機 :8010 暫時建立外部連線。", "Quick Tunnel 不是正式 production 部署；正式環境仍需穩定且受保護的推論服務。"],
        ["正式 request／response", "目前補件文件有欄位說明與結構範例，另有 Prompt 規則命中案例。", "正式 200 組 request／response 尚未取得，狀態保留為 NOT VERIFIED／待 Ollama 端補件。"],
    ], [4.0, 7.5, 5.0], 8.0)
    elements.append(ollama_security_table._tbl)
    new_body(doc, "因此口試時我會把 Ollama 說成『個人化妝容文字建議與 Prompt 組合層』，而不是主要臉部辨識模型。它的價值在於把已經結構化的五官結果、Style 與使用者需求轉成可讀建議，同時由 Server 端保留輸入證據、固定 Style 規則、欄位驗證與 fallback。", elements)

    new_heading(doc, "（六）商品推薦演算法與排序流程", elements, 3)
    new_body(doc, "商品推薦端新增的重點，是把一般商品清單、商品搜尋、商品詳情延伸推薦、臉部分析個人化推薦與會員行為推薦分開。一般清單和搜尋本質上是查詢與排序，不應因為畫面上使用『推薦』字樣就被解釋成已經讀取使用者膚色；只有收到 analysisPackage 或會員行為資料時，才稱為個人化推薦。", elements)
    add_figure(doc, ALGORITHM_FLOW, "圖 3-3　商品推薦系統整體流程圖", elements, 16.0)
    new_body(doc, "上圖的判斷點是是否帶有 analysisPackage。沒有時走一般商品清單；有時才解析膚色、四季型、妝容與 Ollama 結構化文字，接著由商品資料庫提供候選，最後進行候選評分、多樣性重排與推薦理由產生。商品資料庫是候選資料來源，不是 Ollama 自行生成商品。", elements)
    add_figure(doc, ALGORITHM_ACTIVITY, "圖 3-4　個人化推薦演算法活動圖", elements, 16.0)
    new_body(doc, "活動圖把同一筆個人化請求拆成可以重現的步驟：先驗證資料包與商品候選，再並行計算 Lab／CIEDE2000、四季型與冷暖底調、使用者風格字典以及 Ollama JSON 偏好詞，之後依 Lab 是否可靠選擇粉底加權或後備計分，最後做品牌、系列與近分穩定輪替並回傳推薦結果。", elements)

    recommendation_entry_table = new_table(doc, ["推薦入口", "使用資料", "排序／比對方式", "是否個人化"], [
        ["一般商品清單", "商品名稱、品牌、類別、價格、狀態。", "依關鍵字、類別、品牌與價格篩選，再依指定欄位排序。", "否"],
        ["商品搜尋結果", "查詢字串與商品文字欄位。", "符合條件後依名稱、價格、新舊或預設順序排列。", "僅依當次查詢"],
        ["商品詳情／同系列色號", "目前粉底與同系列色號 Lab。", "找出目前色號、較亮色與較深色；MAC 額外遵守 N／NC／NW 色調軌道。", "否"],
        ["商品詳情／同品牌其他系列", "目前粉底及同品牌不同系列 Lab。", "以 CIEDE2000 由近至遠，每個系列保留一項。", "否"],
        ["商品詳情／跨品牌近似色", "目前粉底與其他品牌粉底 Lab。", "排除同品牌後，以 CIEDE2000 選出各品牌近似色。", "否"],
        ["商品詳情／相似商品", "目前商品、類別、色彩、價格與文字標籤。", "色彩 40%、文字／風格 25%、類別 20%、價格 15%。", "否"],
        ["臉部分析個人化推薦", "膚色 Lab、四季型、底調、妝容與 Ollama 建議。", "多訊號加權、避用詞扣分、類別與品牌多樣性重排。", "是"],
        ["會員行為偏好推薦", "收藏、試妝保存、購物車與商品資料。", "收藏 1.0、試妝 0.8、購物車 0.65 建立品牌與類別偏好。", "是；相容／舊版引擎"],
    ], [4.0, 6.0, 5.0, 2.0], 7.8)
    elements.append(recommendation_entry_table._tbl)
    new_body(doc, "這張表的重點是把資料來源和個人化程度標出來。否則同一個商品在清單頁、商品詳情頁和臉部分析結果頁都叫推薦，使用者會以為全部都依自己的膚色排序；實際上它們使用的資料與演算法不同。", elements)

    recommendation_data_table = new_table(doc, ["資料區段", "主要欄位", "用途"], [
        ["faceAnalysis", "skinTone.lab。", "計算粉底與膚色的 CIEDE2000 色差。"],
        ["faceAnalysis", "skinTone.season、undertone。", "比對春夏秋冬與冷暖底調。"],
        ["analysisPackage", "style。", "使用者明確選擇的妝容風格。"],
        ["generativeText", "styleTags、preferredColors、finishTags。", "Ollama 結構化偏好。"],
        ["generativeText", "avoidTags、avoidColors、advice。", "避用條件與自然語言後備提取。"],
        ["商品資料庫", "lab、hex、seasonTags、undertone。", "商品色彩與季型特徵。"],
    ], [4.0, 7.0, 6.0], 8.2)
    elements.append(recommendation_data_table._tbl)
    new_body(doc, "粉底的主要比較使用使用者 skinTone.lab 和商品 lab 計算 CIEDE2000，色差越小表示在相同量測條件下越接近，再將色差轉成 exp(-ΔE00／8) 的衰減分數。文件端記載粉底總分中 Lab 色差占 70%，其餘再合併季型、風格、Ollama 偏好與庫存；實際每個商品的 scoreBreakdown 仍要以 API 回傳核對，不能只看總分。", elements)
    recommendation_weight_table = new_table(doc, ["商品類別", "計分重點", "補件文件記載的現行權重"], [
        ["粉底", "Lab 色差、季型、風格、Ollama 偏好、庫存。", "70%／12%／8%／5%／5%"],
        ["唇彩", "風格、季型、Ollama 偏好、臉部特徵、庫存。", "45%／20%／20%／5%／10%"],
        ["其他彩妝", "色彩、風格、季型、Ollama 偏好、臉部特徵、庫存。", "20%／35%／20%／15%／5%／5%"],
    ], [4.0, 8.0, 4.5], 8.2)
    elements.append(recommendation_weight_table._tbl)
    new_body(doc, "上表保留演算法端補件原本的權重排列，但文件沒有另外提供每一列百分比與欄位的一一對應順序，所以我不自行替它增加對應解釋。正式答辯若要逐項說明，仍應以演算法程式或 API 的 scoreBreakdown 再核對。", elements)

    new_heading(doc, "商品推薦 API、前端呈現與結果證據", elements, 3)
    recommendation_api_table = new_table(doc, ["前端畫面／元件", "呼叫來源", "應呈現內容"], [
        ["商品清單／搜尋頁", "GET /api/products。", "符合篩選的商品與清楚的目前排序方式；不標示為膚色個人化。"],
        ["商品詳情頁", "GET /api/products/{id}。", "商品本體、同系列色號、同品牌其他系列與跨品牌近似色。"],
        ["相似商品區塊", "GET /api/products/{id}/similar。", "相似商品與 lighter、darker、same_brand、budget_alt 或 same_style_alt 關係。"],
        ["跨品牌色號區塊", "GET /api/products/{id}/shade-matches。", "其他品牌粉底、色號、ΔE00 與相似度。"],
        ["個人化妝容結果", "POST /recommend-products。", "完整妝容、主粉底、替代色號、理由與 scoreBreakdown。"],
        ["會員偏好區塊", "會員推薦相容端點。", "依收藏、試妝與購物車推算的偏好；畫面要標示資料依據。"],
    ], [5.0, 5.5, 6.0], 8.0)
    elements.append(recommendation_api_table._tbl)
    recommendation_output_table = new_table(doc, ["回傳欄位", "說明"], [
        ["recommendations.styleDictionary", "字典版本及是否成功套用。"],
        ["recommendations.personalizationInputs", "實際讀取的 Lab、季型、風格及 Ollama 詞彙。"],
        ["products[].scoreBreakdown", "各項評分明細。"],
        ["foundationMatchStatus", "主粉底色差與色號狀態。"],
        ["foundationSameBrandAlternatives", "同品牌其他系列替代選項。"],
        ["foundationCrossBrandAlternatives", "跨品牌近似色。"],
    ], [6.5, 10.0], 8.2)
    elements.append(recommendation_output_table._tbl)
    new_body(doc, "前端不能只顯示 Ollama 的文字而忽略後端實際商品 ID，也不能把一般清單的預設排序包裝成膚色個人化推薦。若同一商品同時符合多個入口，畫面應保留來源標籤，例如同品牌其他系列、跨品牌近似色或依暖春型推薦，讓使用者知道這一項為什麼出現。", elements)

    new_heading(doc, "（七）演算法端新增內容的困難與驗證", elements, 3)
    new_body(doc, "演算法端補件把新增內容整理成幾個實際遇到的問題。下面的處理方式是補件文件記載的版本；其中『完成』只表示文件描述該項修改或驗證已完成，不能延伸成所有資料來源、線上版本和完整 E2E 都已經驗收。", elements)
    recommendation_problem_table = new_table(doc, ["困難", "原因", "處理方式"], [
        ["不同使用者取得相同商品", "舊標籤 daily、natural 過度集中。", "改用 Lab、HSL、季型和 NLP 多訊號計分。"],
        ["MAC NW7 出現頻率過高", "服務曾明定 MAC 為粉底錨點。", "移除品牌硬編碼，依實際總分選主粉底。"],
        ["同系列之外沒有替代品", "原介面只提供較亮與較深色。", "新增同品牌其他系列及跨品牌替代清單。"],
        ["Ollama 回覆格式不固定", "自由文字可能漏欄位或誤判否定語意。", "JSON Schema 優先，並保留受控詞彙後備解析；完整 Schema 契約仍需與 Ollama 端核對。"],
        ["相近商品排序長期固定", "大量商品分數完全或幾乎相同。", "使用分析包 ID 做小幅穩定輪替，保持相同資料包可重現。"],
        ["照片與商品色彩受環境影響", "光源、白平衡、螢幕及品牌色票不等於實測膚色。", "保留試色聲明，避免宣稱絕對準確。"],
        ["一般清單與個人化推薦混淆", "多個畫面都以推薦字樣呈現，但資料來源不同。", "逐一標示入口、端點、演算法與是否個人化。"],
        ["線上服務與資料庫相容引擎並存", "兩處皆有推薦路由，可能造成文件或前端誤接。", "以現行 Product Service 為主，舊引擎明確標為相容用途。"],
    ], [4.2, 6.0, 5.8], 7.8)
    elements.append(recommendation_problem_table._tbl)
    new_body(doc, "演算法端文件記載的 2026 年 9 月 6 日驗證案例，使用三組資料包進行本機線上服務驗證：暖春韓系資料取得 CHANEL B10、暖秋港風資料取得 ESTEE LAUDER 商品、冷夏千金資料取得 CHANEL B30；三組腮紅、唇彩、眼影及修容商品 ID 不同，回傳 season 分別為 spring、autumn、summer。文件另記載自動測試共五項通過，涵蓋品牌不強制、同品牌其他系列、Ollama 文字提取、季型正規化及穩定輪替。這些數字與案例是新增演算法文件提供的紀錄，不延伸解讀成模型準確率或完整線上 E2E。", elements)
    new_body(doc, "CIEDE2000 的公開技術依據保留原始連結：https://www.cie.co.at/publications/colorimetry-part-6-ciede2000-colour-difference-formula-1；影像色差評估方法：https://www.cie.co.at/publications/methods-evaluating-colour-differences-images。Ollama 結構化輸出與 Generate API 也保留原始連結：https://docs.ollama.com/capabilities/structured-outputs、https://docs.ollama.com/api/generate。", elements)
    insert_elements_before(target, elements)


def add_model_worklog_under_implementation(doc):
    target = find_paragraph(doc, lambda t: t.startswith("陸、") and "結論及未來發展" in t)
    elements = []
    worklog_number = next_subheading_number(doc, "伍、", target)
    new_heading(doc, f"{chinese_number(worklog_number)}、臉部分析模型訓練工作流", elements, 2)
    new_body(doc, "下面是我實際做模型的工作流。我沒有只記最後選到哪一個架構，而是把每次跑實驗前的問題、當時的判斷、執行方式、遇到的錯誤和最後留下的檔案都列出來。這樣可以說明模型不是突然變成現在的版本，而是經過資料檢查、失敗重跑、切分修正和線上驗證逐步形成。", elements)

    timeline = [
        ["2026-07-13", "先檢查現行規則式，再建立 ROI CNN baseline。", "規則式在 validation 幾乎退化成固定答案：眉型大量為彎月眉、眼型約 96% 為桃花眼、鼻型約 98% 為標準鼻；CNN 按人切分約臉型 0.475、眉型 0.589、眼型 0.378、鼻型 0.666、唇型 0.452。", "新增 `eval_rule_baseline.py`、`train_basic_cnn_roi.py`、`basic_roi_shadow.py`；模型先 shadow，不直接覆蓋使用者結果。"],
        ["2026-07-13", "把 MobileNetV3-small 匯出 ONNX，並用 Torch／ONNX Runtime 對照。", "torch 2.12 的新 exporter 讓權重拆成 `.onnx` 和 `.onnx.data`，部署時少一個檔就會靜默失敗。", "改用單檔 ONNX、另存 `.pt`；batch=8 的最大輸出差約 3.36e-05 以內，預測一致。"],
        ["2026-07-14", "加入 DINOv2 frozen encoder＋線性分類器做第三種方法。", "眼型在小資料集上 fine-tune CNN 過擬合，DINOv2 的 frozen feature 在部分 fold 較好，但不能只用一次結果決定正式模型。", "產出 DINOv2 CV、LogReg／SVM head 與 shadow 規格，先不放正式輸出。"],
        ["2026-07-19", "整理模型資產、版本與 shadow prediction。", "發現模型檔、類別檔、DINO head 和實際服務目錄容易不同步；只看檔案存在不能證明服務載入正確版本。", "開始保存 model record、模型版本與分類來源，建立後續 manifest 思路。"],
        ["2026-07-22", "重新檢查鼻型類別與現行分類來源。", "窄鼻的鼻翼比例中位數反而比標準鼻寬，規則條件和人工命名對不起來；保留窄鼻會讓規則與模型都學一個不清楚的題目。", "窄鼻併入標準鼻，並逐處移除過期標籤與舊 suppression。"],
        ["2026-07-24", "做資料清理、內容 hash、身份分組和同 protocol 的規則／CNN 比較。", "發現 314 個多餘重複檔，195 組同一張圖跨類別；舊 identity map 過期，鼻型 validation 實際只量到少數樣本。", "套官方分類表、依內容 hash 去重、列出 `label_conflicts.json`、重建 identity map，正式改用 cluster identity split。"],
        ["2026-07-24", "驗證 PRO 側面鼻型不能沿用 BASIC 的 landmark ROI。", "Face Mesh 側臉成功率約 73.5%，而且塌鼻約 60.4%、翹鼻約 93.4%，失敗不是平均分布，直接丟掉會偏向好偵測類別。", "PRO 改用整張側臉 resize 224，不做 landmark ROI；先把側面鼻型當獨立模型任務。"],
        ["2026-07-24", "修正 Windows 非 ASCII 專案路徑造成 MediaPipe 初始化失敗。", "C++ 層用系統編碼開檔，搬到含中文路徑後找不到 face landmark binarypb，但檔案其實存在。", "新增 `mediapipe_ascii.py` 自動複製到 ASCII 路徑，並補 Dockerfile COPY；搬機與 Cloud Run 路徑不受影響。"],
        ["2026-07-29", "把模型完整發展歷程、資料夾和部署差異補成文件。", "發現類別合併只做一半、絕對路徑 identity map 會失效，且實驗目錄和線上目錄名稱相近，容易拿錯檔。", "保存 pre/post merge 快照、模型目錄用途、實驗輸出與回復方式，並把踩坑保留在文件裡。"],
        ["2026-07-30", "重新建立 identity map，處理眼型合併與分類表同步。", "眼型搬動 101 張後，舊 map 查不到搬動檔案；identity=-1 的照片會全部留 train，造成 validation 只剩極少數。", "identity=-1 從 315 張降到 2 張；眼型改成現行四類，重訓 CNN／DINO head，並同步前端可選標籤。"],
        ["2026-07-30", "比較臉型 CNN、階層樹與 class weight 的實際效果。", "class weight 可能讓某類搶著被預測；臉型的錯誤集中在心形／鵝蛋與圓形／方形等視覺相近類別。", "臉型由 CNN 提供正式答案，幾何方法保留作分析與 fallback；評估時改看 precision、recall 與 confusion matrix。"],
        ["2026-07-31", "BASIC 與 PRO 主要架構改為 ConvNeXt-Tiny，DINOv2 退居實驗／shadow。", "相同 5-fold 與訓練設定下，ConvNeXt 對眼型、鼻型、唇型和整體平衡較好，但檔案約 110 MB、部署成本高於 MobileNet。", "更新 runtime 模型、類別檔與 manifest；不再把 DINOv2 實驗檔說成正式線上模型。"],
        ["2026-08-06", "建立固定 holdout，並做合併前後和 seed 的對照。", "保留 613／2298 張、涵蓋 197 個 identity；同資料只換 seed，鼻型分數可在 0.731～0.873 間晃，單次分數不可靠。", "建立 `holdout_split_v1.json` 與 `holdout_scores.json`；明確記錄 v1 被全資料重訓花掉後不能再評估線上模型。"],
        ["2026-08-06", "選 seed 43 的 ConvNeXt bundle 做一次歷史線上更新。", "不加 `--architecture` 或不給 `--out-dir` 會把線上 ConvNeXt 靜默覆蓋成 MobileNet；只換本地檔但不更新 manifest，部署又會下載回舊模型。", "seed 43、bundle 20260806、manifest 與 GCS hash 對齊；用 12 張照片×5 部位核對，線上與新模型 60／60 一致。"],
        ["2026-08-07～10", "整理資料還原、模型備份、前端／本機服務與 Cloud Run 健康檢查。", "health 200 只能表示服務活著，不能表示載入的是新模型；本機訓練資料同步也可能因 Unicode 檔名或命令逾時未完整。", "保留模型與資料備份、記錄 revision／image／hash，測試 BASIC／PRO 可推論；未完成的會員、商品、付費渲染 E2E 明確標記 NOT RUN。"],
        ["2026-08-11～14", "做幾何、CNN、DINOv2 與 feature fusion 的同 fold 比較。", "混合規則不一定比純 CNN 好；鼻型 fusion 約 0.8920 有較明顯訊號，其他部位提升接近 noise，不能全部一起採用。", "保留鼻型 fusion 研究方向，其他任務仍以純 ConvNeXt 為主要判斷；新增完整 per-class 與 κ 等報告。"],
        ["2026-08-17", "補完眼型與唇型 ConvNeXt 評估。", "同一份 2298 筆 ROI cache、5-fold、40 epochs 下，ConvNeXt 約臉型 0.541、眉型 0.537、眼型 0.653、鼻型 0.885、唇型 0.626；微笑唇仍受樣本量限制。", "確認架構增益集中在原本弱類別；Windows 自動更新中斷訓練與 summary 覆寫問題被記錄並修正流程。"],
        ["2026-08-24～26", "把使用者修正、後台人工覆核、training worker 與 failure alert 接起來。", "使用者修正不等於可直接訓練；GCS 沒有實際存圖、管理員尚未審核、worker 失敗但 heartbeat 還在跳，都可能造成假成功。", "建立 jobId→feedbackId→runId；僅採用有 consent、實際影像、管理員決定的資料；training run append-only，失敗寫回原因並告警。"],
        ["2026-09-03", "把模型 promotion 做成可重複、可驗證、可回滾的流程。", "訓練產物、GCS bundle、manifest、Cloud Run revision 如果只有一段沒更新，線上可能仍然是舊模型。", "目前以 `tools/face_models_manifest.json`、`models/training_runs/<runId>/`、promotion ledger、SHA-256、health／smoke 和 rollback 作為模型上線證據。"],
    ]
    table = new_table(doc, ["日期", "我做了什麼", "我發現的問題／判斷", "留下的成果與改善"], timeline, [2.6, 5.0, 7.2, 6.0], 7.8)
    elements.append(table._tbl)

    new_heading(doc, f"{chinese_number(worklog_number + 1)}、模型訓練方法與實驗結果", elements, 2)
    new_body(doc, "正式訓練以每個五官部位獨立分類為主。先用 MediaPipe Face Mesh 找 ROI，再轉 RGB、resize、normalization，使用 identity-aware 5-fold 交叉驗證。訓練主要採 AdamW、WeightedRandomSampler、label smoothing 0.05、亮度／對比度與小位移增強，不做水平翻轉，避免把落尾眉、左右不對稱的唇形或眼角方向餵成錯標籤。", elements)
    new_body(doc, "我主要看 Macro Accuracy、Balanced Accuracy、Macro-F1、每類 precision／recall 和 confusion matrix。Macro Accuracy 是先算每個類別的 recall，再平均；它不是把所有樣本混在一起的普通 accuracy。資料量小時，單次結果可能受 fold 組成和 seed 影響，所以我會把平均值、標準差、每 fold 和資料版本一起寫。", elements)
    table = new_table(doc, ["方法／條件", "臉型", "眉型", "眼型", "鼻型", "唇型"], [
        ["規則式／幾何（同 fold）", "0.449", "0.448", "0.379", "0.782", "0.336"],
        ["DINOv2＋線性 head", "0.424", "0.543", "0.473", "0.846", "0.446"],
        ["MobileNetV3-small", "0.521", "0.511", "0.562", "0.849", "0.553"],
        ["EfficientNet-B0", "0.564", "0.612", "0.607", "0.855", "0.561"],
        ["ResNet-50", "0.604", "0.587", "0.660", "0.877", "0.578"],
        ["ConvNeXt-Tiny", "0.561", "0.603", "0.693", "0.881", "0.640"],
        ["AlexNet", "0.494", "0.422", "0.628", "0.867", "0.396"],
    ], [4.8, 2.3, 2.3, 2.3, 2.3, 2.3], 8.5)
    elements.append(table._tbl)
    new_body(doc, "ConvNeXt-Tiny 不是每一個單項都第一，例如臉型 ResNet-50 約 0.604 高於 ConvNeXt-Tiny 的 0.561；我選 ConvNeXt 是因為它在五個任務的整體平衡較好，眼型、鼻型、唇型的結果較有優勢，也能統一接到 ONNX 與目前 runtime。這個選擇的代價是模型檔較大、CPU 推論和 Cloud Run 記憶體成本較高。", elements)
    new_body(doc, "類別合併也是實驗結果的一部分。眼型把高度重疊類別整理成現行四類後，曾觀察到約 0.473→0.542 的改善；唇型把 M 型唇併入花瓣唇後，約 0.492→0.560。這些提升不能單獨解讀成模型架構變好，因為題目本身也被重新定義；所以我在工作流中同時保留合併前後的類別數和資料版本。", elements)

    new_heading(doc, f"{chinese_number(worklog_number + 2)}、UAT 測試工作流", elements, 2)
    new_body(doc, "我前面要求調整的很多介面，其實都是 UAT：用實際使用者、管理員與維運者的操作去驗證系統是否真的能完成任務。下面的欄位固定為「發現問題、為什麼有問題、改善過後」，不只記錄畫面長什麼樣，也記錄資料、權限、錯誤訊息和下一步是否能接續。", elements)
    uat = [
        ["臉部分析尚未完成時，前端把 409／暫時狀態當成失敗。", "背景分析需要時間，使用者會重送照片，造成多個 job，也不知道原本工作其實還在跑。", "我把 jobId、狀態查詢與結果查詢分開，未完成維持等待／輪詢，只有真正失敗才顯示錯誤。"],
        ["渲染第一次逾時後自動重試，畫面顯示失敗。", "伺服器已建立原始 job，第二次只是撞到進行中的工作；沒有原始 jobId 就無法接續。", "409 回傳原始 jobId 與 resultToken，前端接著輪詢原工作，不再把進行中誤判為失敗。"],
        ["管理員要比較妝前／妝後，妝前圖卻被權限擋住。", "只看妝後圖無法判斷人臉是否被替換；但全面放寬會讓陌生人讀到生物特徵資料。", "只放寬管理員並留下 audit；本人仍可看自己的圖，陌生人沒有 admin 旗標仍被擋。"],
        ["使用者送出回饋後再次修改，系統產生重複紀錄。", "前端允許同一 job 再修改，新增文件會灌大統計分母並留下舊訓練標籤。", "用 jobId 覆寫同一筆回饋；改回原答案時清除 corrected 與 training record。"],
        ["沒有 consent、沒有圖片或 GCS 實際沒存圖，後台仍像是可送訓。", "標籤存在不代表影像貢獻成功，contributed 說謊會造成空白樣本或零樣本訓練。", "contributed 只在實際成功保存至少一張圖時為 true；回饋可以保留，但不能當可訓練影像。"],
        ["舊回饋沒有 reviewStatus，後台可能把它當成已採用。", "沒有狀態不代表已審核，預設 approved 會讓未覆核標籤進入送訓。", "缺 reviewStatus 統一視為 pending，最新資料在前，只列出真正有差異的 changes。"],
        ["後台有回饋但樣本影像是空白。", "GCS 讀取失敗、檔案過大或 ROI 沒成功保存時，空白圖不代表有訓練樣本。", "保存結果與 contributed 分開記錄，沒有實際樣本不能正常送訓，畫面顯示缺圖／讀取失敗。"],
        ["後台採用／退回所有錯誤都顯示 503。", "不存在、權限不足和服務掛掉的處理方式不同，混成 503 會讓管理員對不存在的資料一直重試。", "保留可處理的 4xx，只有真正上游不可用才回 503，並確認 CSRF、actor 和 admin 都通過。"],
        ["訓練失敗時 heartbeat 還在跳，後台沒有失敗原因。", "機器活著不等於訓練程序成功，管理員無法判斷目前該等待還是重試。", "先寫回 status=failed 與 error，再盡力推失敗指標；空錯誤也補可讀訊息。"],
        ["管理員以為某個 training run 被刪除。", "run 是模型工作流的證據，刪除或只留下摘要會無法證明當時用了哪些資料與模型。", "training runs 改為 append-only，保留 startedAt、finishedAt、modelBefore、modelAfter、metrics、error。"],
        ["會員名冊讀取失敗時，儲存稽核把全部資料列成孤兒。", "空名冊和真的沒有會員不同，管理員照錯誤清單清除會刪掉仍有主人的資料。", "名冊不可讀時停止稽核並回報錯誤；分開會員、無儲存會員、訪客與真正 orphan，不回傳 email。"],
        ["商品上游 401／403 被前端顯示成請重新登入。", "管理員 session 已有效，問題是商品金鑰或 URL，重登無法修復。", "轉成 PRODUCT_UPSTREAM_REJECTED 的 502，明確說登入有效；404／409／422 保留原資料語意。"],
        ["商品新路徑被 Gateway 自己 404。", "路由白名單未放行時，看起來像商品上游沒做端點，難以判斷責任在哪一端。", "補 route allowlist 與 method 檢查，測試區分 Gateway 沒開和上游不存在。"],
        ["前端仍有固定 style.advice 或自己切割 LLM 長文。", "固定文字會冒充 AI 成功，前端切割自然語言也會隨 response 格式改變而壞掉。", "正式方向改為結構化 response，前端只顯示中文建議；正式 200 契約尚未取得，這項保留待完成。"],
        ["Ollama 不可達時仍顯示上一段或固定建議。", "使用者會以為這次照片分析成功，實際建議可能不是本次結果。", "不可用時 fail closed，回傳 OLLAMA_UNAVAILABLE／EXTERNAL_TEXT_UPSTREAM_DISABLED，不使用假 fallback。"],
        ["後台 sampleCount 容易被理解成照片數或使用者數。", "實際上 selections 可能是一筆回饋的多個部位，誤讀會錯估訓練資料量。", "保存 selections 快照並寫清楚 sampleCount 定義，另核對實際 GCS 物件數與 feedbackIds。"],
        ["使用者確認答案與使用者修正被混成同一種 accuracy。", "確認是接受目前答案，修正才是不接受；混在一起會灌高模型表現。", "分開 acceptance evaluation、predicted、agreed、corrected、contributed；明確說 acceptance 不是 accuracy。"],
        ["五官基本資料和額外側臉鼻型加總對不起來。", "只看總數不知道多出的資料屬於哪個部位，演算法端無法追查。", "彙總增加 extraParts 與 consistencyChecks，BASIC 五部位和 PRO 側臉鼻型分開計算。"],
        ["本地訓練完成，線上服務卻仍讀舊模型。", "訓練輸出、GCS、manifest 和 Cloud Run revision 是不同步驟，只看本地 metrics 不代表上線。", "加入 modelVersion、SHA-256、manifest、promotion ledger、health、smoke 和 rollback。"],
        ["前端只做 node --check 就被當成完整驗收。", "語法正確不代表登入、分析、渲染、收藏、後台與下游服務都能完成。", "把單元測試、API 契約、前端 smoke、UAT、Cloud Run health 和完整 E2E 分開報告；未執行標記 NOT RUN。"],
    ]
    table = new_table(doc, ["發現問題", "為什麼有問題", "改善過後"], uat, [6.5, 6.8, 6.5], 7.8)
    elements.append(table._tbl)
    new_body(doc, "這張表的自動化證據主要在 `tests/ai_gateway_test.py`、`tests/render_api_test.py`、`tests/face_feedback_test.py`、`tests/face_contributions_test.py`、`tests/training_run_store_test.py`、`tests/export_feedback_aggregate_test.py`，以及前端 `node --check` 和 smoke test。自動化測試不是取代人工 UAT，而是把曾經發生過的問題固定下來，避免下一次修改介面或後台時又回到原本狀態。", elements)

    new_heading(doc, f"{chinese_number(worklog_number + 3)}、模型成果檔案與部署驗證", elements, 2)
    new_body(doc, "我的地端成果不是只有一個模型檔，而是每次訓練都應該留下 runId、資料版本、類別版本、訓練參數、metrics、checkpoint、ONNX、類別檔與 hash。現行主要位置如下；如果只看到檔案存在，還要再核對它是否被 manifest 指定、是否被服務載入，以及是否有對應的 Cloud Run revision。", elements)
    table = new_table(doc, ["成果", "位置／名稱", "驗證方式"], [
        ["BASIC 五官模型", "`models/basic_features_roi/face_shape.onnx`、`brow_shape.onnx`、`eye_shape.onnx`、`nose_shape.onnx`、`lip_shape.onnx`", "ONNX 可載入、classes 對得上、SHA-256 和 manifest 一致。"],
        ["PRO 側面鼻型", "`models/pro_nose_side/nose_shape_side.onnx`、`nose_shape_side_classes.json`", "獨立檢查 5 類、整張側臉輸入與獨立指標，不混入 BASIC。"],
        ["每次地端訓練", "`models/training_runs/<runId>/`", "summary、metrics、模型檔、參數與失敗原因同一批保存。"],
        ["現行 manifest", "`tools/face_models_manifest.json`，版本 `20260903_brow_nose`", "核對 GCS prefix、檔案大小、hash 與服務實際 revision。"],
        ["訓練主程式", "`training/train_basic_cnn_roi.py`", "固定部位、架構、seed、epochs、learning rate、identity split 與 export 參數。"],
        ["模型 promotion", "`tools/promote_model.py`、`tools/promotion_worker.py`", "檢查類別一致性、metrics、hash、上傳、部署、health／smoke 與回滾。"],
    ], [4.0, 9.5, 6.3], 8.4)
    elements.append(table._tbl)
    new_body(doc, "目前文件內的歷史結果，例如 ConvNeXt-Tiny 五折 Macro Accuracy 臉型 0.561、眉型 0.603、眼型 0.693、鼻型 0.881、唇型 0.640，必須和當時的資料、類別與 protocol 一起引用。工作區另外存在現行 `cv_report_summary.json` 的 accuracy、Balanced Accuracy、Macro-F1，它們不是同一張考卷，不能直接混成一個最新準確率。", elements)
    new_body(doc, "模型工作真正完成的定義是：資料與類別版本清楚、訓練可以重現、結果可以解釋、模型檔和類別檔一致、服務載入正確版本、線上 smoke 通過，而且出問題時能回到上一版。只有完成這些步驟，我才會把它寫成已部署；單純看到地端訓練跑完，不代表線上使用者已經用到新模型。", elements)

    new_heading(doc, f"{chinese_number(worklog_number + 4)}、Worker 技術細節與完成界線", elements, 2)
    new_body(doc, "模型訓練和模型換版不是同一個動作。管理員在後台按下送訓或升版後，Gateway 只負責建立 queued 工作並留下請求身分；真正需要訓練機檔案、模型輸出、gcloud 認證與服務部署的工作，交由本機 Worker 執行。這樣才能把 face_training_runs、face_model_promotions、face_service_deployments 的狀態、runId、版本、metrics、manifest、hash 和失敗原因留在同一條工作流裡。", elements)
    new_body(doc, "目前 ONNX 模型檔的體積約為每個 111 MB，訓練機與 Cloud Run 的檔案系統及認證環境不同，所以 Cloud Run 後台不能直接執行地端訓練。Worker 的功能是把後台決定轉成可追蹤的訓練、升版與部署工作；Worker 本身不是模型，也不能把 queued、running 或 health 200 直接當成模型已換版。", elements)
    worker_role_table = new_table(doc, ["元件／程式", "實際責任與資料集合", "目前完成界線"], [
        ["training_worker.py", "執行訓練，讀寫 face_training_runs，回報 stage、progress、metrics、成功或失敗原因；訓練時寫入 face_training_workers。", "有訓練 heartbeat、啟動回收自己中斷的 running 批次與 Windows 睡眠抑制；claim 仍不是原子操作。"],
        ["promotion_worker.py", "執行 promotion、模型檔搬移、manifest／hash 檢查、build 與部署，讀寫 face_model_promotions、face_service_deployments。", "沒有 heartbeat；輪詢迴圈每 300 秒做 stale sweep；可用 RELOAD_EXIT_CODE 86 讓外殼重新啟動。"],
        ["Gateway／後台", "依 actor、權限、路由與去重規則建立 queued 工作，提供工作狀態與錯誤給前端。", "不直接訓練或換版；後台按鈕尚未完成實機驗收，不能只用 API 或單元測試宣稱已驗收。"],
        ["Ollama 建議服務", "接收臉部分析結果、妝容風格與使用者需求，產生文字建議；不屬於 promotion_worker 的服務部署清單。", "Ollama 的正式 request／response 與目前通道仍要由該端補齊，不能由 Worker 資料推定。"],
    ], [3.2, 9.0, 5.8], 8.4)
    elements.append(worker_role_table._tbl)
    new_body(doc, "表中的『完成界線』是為了區分已存在的程式行為和還沒做完的保證。training_worker 有 heartbeat，不代表 promotion_worker 也有；promotion_worker 有 stale sweep，也不代表已經具備 lease；promotion ledger 有完整性檢查，也不代表 claim 已經具備並發安全。", elements)

    worker_state_table = new_table(doc, ["工作類型／集合", "實際狀態流程", "識別欄位與工作留"], [
        ["訓練批次／face_training_runs", "queued → claimed → running → done；失敗時為 failed。", "runId 使用 TR- 加 16 位十六進位識別；保存 feedbackIds、selections、sampleCount、workerId、startedAt、finishedAt、metrics、artifact 與 error。"],
        ["換模型／face_model_promotions", "queued → claimed → running → deployed；使用 prepare-only 時可為 prepared；失敗時為 failed。", "promotionId 使用 PM- 加 16 位十六進位識別；保存 runId、parts、stage、version、backup、results、requestedBy。"],
        ["服務部署／face_service_deployments", "queued → claimed → running → deployed 或 failed。", "deploymentId 使用 DP- 加 16 位十六進位識別；services 表示 face、gateway、render 的部署子集；stage 與 note 用來判讀進度。"],
        ["Worker 存活／face_training_workers", "training、idle、offline。", "目前只有 training_worker 寫入 workerId、state、detail、lastSeenAt 與存活指標；promotion_worker 沒有心跳文件。"],
        ["模型指標／face_model_metrics", "保存線上或升版比較所使用的 metrics。", "metrics 必須和資料版本、類別版本、protocol、runId 對照；不能用單一 health 結果代替模型評估。"],
    ], [3.5, 6.0, 8.5], 8.4)
    elements.append(worker_state_table._tbl)
    new_body(doc, "Worker 的 claim 目前是先讀再寫，不是原子操作。程式先讀取工作並確認 status 為 queued，再寫入 claimed、claimedAt、workerId 等欄位；training_worker 與 promotion_worker 都有這個限制。現有 REST 儲存層沒有 transaction 或條件式更新，shared/job_store.py 的 patch_if_status 也沒有被兩支 Worker 使用，所以不能把單 Worker 測試通過解讀成多 Worker 並發安全。", elements)
    new_body(doc, "stale 回收目前也不是完整 lease。training_worker 啟動時只回收 workerId 等於自己的 running 批次；promotion_worker 在輪詢迴圈每 300 秒掃描 claimed 或 running 超過固定 30 分鐘的工作，清除 stage、留下原因並放回 queued。這個判定只看固定時間，沒有 heartbeat、lease expiry 或 claim token 驗證，因此合法但執行超過 30 分鐘的工作可能被誤回收。", elements)
    new_body(doc, "目前只有 training_worker 寫入 heartbeat；它會把 state、detail 與 lastSeenAt 寫入 face_training_workers，也可推送 Cloud Monitoring 存活指標。heartbeat 寫入失敗不會中止訓練。promotion_worker 沒有心跳，這項差異必須保留在文件中。", elements)
    worker_limit_table = new_table(doc, ["項目", "狀態", "目前限制與阻塞原因"], [
        ["Claim 原子性", "NOT DONE", "兩支 Worker 都是先讀再寫；REST 層沒有 transaction 或條件式更新，存在並發取得同一筆工作的風險。"],
        ["Heartbeat／lease 判定 stale", "NOT DONE", "目前只用固定 30 分鐘的 claimedAt 判定，沒有 heartbeat 或 lease expiry；長時間工作可能被誤放回排隊。"],
        ["Claim token 驗證", "NOT DONE", "目前沒有 claim token，後續狀態寫入也沒有驗證持有正確 token 的 Worker。"],
        ["promotion_worker 心跳", "NOT DONE", "只有 training_worker 寫入 face_training_workers 與存活指標，promotion_worker 尚未提供心跳。"],
        ["訓練批次的 feedback 關聯失敗", "未決定", "目前關聯寫入失敗仍不影響 API 回傳，API 仍回 202 queued；是否改成失敗即阻擋尚未決定。"],
        ["後台按鈕實機驗收", "NOT RUN", "後台權限、渲染次數與模型工作按鈕尚未完成實際登入後的點擊驗收。"],
        ["膚色分塊取樣準確率", "NOT VERIFIED", "目前有取樣行為與結果紀錄，但沒有足以判定準確率的人工標註 holdout；不能寫成準確率提升。"],
        ["Render prompt identity lock 關閉後的輸出比對", "NOT VERIFIED", "identity lock 關閉後尚未完成妝前／妝後實際輸出比對，不能宣稱仍保留本人特徵。"],
    ], [4.4, 2.4, 11.2], 8.4)
    elements.append(worker_limit_table._tbl)
    new_body(doc, "以上 NOT DONE、NOT VERIFIED、NOT RUN 與未決定都是目前正式的完成界線。後續只有補上程式、測試、日誌、人工標註或實機操作證據，才可以更新狀態；不能以本機 health、截圖或單次成功執行代替。", elements)

    worker_test_table = new_table(doc, ["測試檔／情境", "目前涵蓋內容", "不能由此測試推出的結論"], [
        ["tests/deployment_queue_test.py", "部署回收、輪詢 stale sweep、避免單一情境重複執行、promotion ledger 完整性。", "不能推出並發 claim 已原子化，也不能取代後台真實登入後的按鈕驗收。"],
        ["tests/training_worker_test.py", "訓練機睡眠抑制的設定與還原。", "不能推出 training_worker 有 claim token、lease 或模型準確率結果。"],
        ["tests/training_run_store_test.py", "訓練失敗時的狀態與告警指標。", "不能推出 feedback 關聯失敗的處理取捨已經決定；目前 API 仍回 202 的行為仍待確認。"],
        ["tests/promotion_margin_test.py", "誤差計算與無法計算時的保守阻擋。", "不能推出 identity lock 關閉後輸出保留本人特徵，也不能推出膚色分塊取樣的人工準確率。"],
        ["Worker 並發 claim", "目前沒有兩個 Worker 同時 claim 同一筆工作的完整測試。", "此情境是 NOT DONE；單 Worker 通過不代表多 Worker 安全。"],
    ], [4.5, 7.6, 5.9], 8.2)
    elements.append(worker_test_table._tbl)
    new_body(doc, "測試通過只代表對應案例通過，不能取代尚未執行的並發、長時間、真實雲端、人工標註與實機 UAT。", elements)

    new_heading(doc, f"{chinese_number(worklog_number + 5)}、出版與原始資料來源", elements, 2)
    new_body(doc, "本節採出版資料常用的來源格式：『[編號] 作者／機構。（年份或 n.d.）。資料標題。網址或原始檔案位置。』公開技術文件以 n.d. 表示原頁面未提供可直接核對的出版年份；本專案程式、測試與工作留則保留原始檔案位置。網址只作為來源與查核入口，不代表本次已重新驗證服務目前可用。", elements)
    source_table = new_table(doc, ["資料來源類型", "出版／原始資料格式", "用途與可信度邊界"], [
        ["[S1] 前端原始程式", "妝識你的美專題前端。（2026）。`js/api.js`、`js/image-worker.js`。C:\\Users\\isach\\Downloads\\專題前端 (Remix) (Remix) (1).zip。", "核對照片欄位、ImagePipeline、Worker 壓縮、尺寸與 data URL；本次未在這兩個檔案確認像素提亮。"],
        ["[S2] 臉部分析與模型程式", "妝識你的美專案。（2026）。`face/`、`training/`、`models/`。C:\\Users\\isach\\PycharmProjects\\PythonProject12。", "核對 Face Mesh、ROI、分類模型、資料切分、訓練與模型檔；程式存在不等於線上版本一定已載入。"],
        ["[S3] Worker 與測試", "妝識你的美專案。（2026）。`tools/training_worker.py`、`tools/promotion_worker.py`、`tests/`。C:\\Users\\isach\\PycharmProjects\\PythonProject12。", "核對 Worker 狀態、工作留、測試涵蓋與未完成界線；測試只證明被測情境。"],
        ["[S4] 前端正式部署原始網址", "妝識你的美專題。（2026）。前端正式站。https://decorate-me.web.app。", "原始部署入口；網址原樣保留，但專題名稱在本文統一為妝識你的美，站點目前狀態仍需重新驗證。"],
        ["[S5] Face Basic／Face Pro／Render", "妝識你的美專題。（2026）。服務健康檢查。https://face-basic-258021445391.asia-east1.run.app/health；https://face-pro-258021445391.asia-east1.run.app/health；https://replicate-render-258021445391.asia-east1.run.app/health。", "原始工作留中的服務入口；health 200 只能表示服務回應，不代表模型版本、完整 E2E 或圖片輸出已驗證。"],
        ["[S6] MediaPipe", "Google。（n.d.）。MediaPipe Face Landmarker。https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker。", "臉部關鍵點與 landmark 方法來源。"],
        ["[S7] Ollama", "Ollama。（n.d.）。Ollama API 文件。https://docs.ollama.com/。", "文字建議服務 API 的公開技術來源；不代表本專題的正式通道已由本文件重新驗證。"],
        ["[S8] Replicate", "Replicate。（n.d.）。API 文件。https://replicate.com/docs。", "渲染服務上游串接的公開技術來源。"],
        ["[S9] 色差方法", "CIE。（n.d.）。Colorimetry Part 6 CIEDE2000。https://cie.co.at/publications/colorimetry-part-6-ciede2000-colour-difference-formula。", "粉底與商品色號比較的公開方法來源。"],
        ["[S10] GCS／Firebase", "Google Cloud。（n.d.）。Signed URLs 與 Object Lifecycle Management。https://cloud.google.com/storage/docs/access-control/signed-urls；https://cloud.google.com/storage/docs/lifecycle。Firebase。（n.d.）。Hosting。https://firebase.google.com/docs/hosting。", "核對私人媒體、物件生命週期與前端部署概念；實際 bucket、權限與服務狀態仍以本專案設定及驗收為準。"],
        ["[S11] 演算法端新增技術文件", "演算法端。（2026）。妝識你的美商品推薦系統與演算法技術文件。C:\\Users\\isach\\Downloads\\Decorate_Me_智慧彩妝推薦系統_商品推薦技術文件.docx。", "補充商品推薦入口、CIEDE2000／HSL／四季型、排序權重、API 欄位、困難處理與驗證案例；文件記載不取代程式與線上端點核對。"],
        ["[S12] Ollama 端新增技術文件", "Ollama 端。（2026）。妝識你的美個人化妝容建議模組詳細技術說明。C:\\Users\\isach\\Downloads\\DECORATE_ME_Ollama_個人化妝容建議模組_詳細技術說明.md。", "補充 Gemma3、LLaVA、Suggestion Service、JSON 驗證、Fallback、Render Prompt、安全與開發測試架構；正式 200 組 request／response 仍未取得。"],
    ], [3.5, 10.0, 4.5], 8.0)
    elements.append(source_table._tbl)
    new_body(doc, "來源中的正式服務 URL、歷史 Quick Tunnel、本機網址與公開技術文件要分開判讀。歷史網址可以保留作為工作留，但不能因此宣稱目前固定端點；本機路徑可以指向原始程式，但不能把本機檔案存在寫成雲端已部署。", elements)
    insert_elements_before(target, elements)


def add_gap_under_conclusion(doc):
    target = None
    # 結論章節是原文件最後一個大標，因此把補件內容放在其現有未來發展內容後面。
    for p in doc.paragraphs:
        if p.text.strip().startswith("陸、") and "結論及未來發展" in p.text:
            target = p
            break
    if target is None:
        return
    # 放在 sectPr 前面，避免把內容插到 Word body 的結尾節點之後。
    elements = []
    new_heading(doc, "三、目前無法由我們端自行補齊的跨端資料", elements, 2)
    new_body(doc, "目前我們自己可以從程式、測試、地端模型與既有紀錄補上的內容，我已經放進前面各個原本的大標下；但下列資料只掌握在各端負責人手上，我不能自行猜測。這些內容會分別用 Markdown 文件向 Ollama、演算法、爬蟲、資料庫端索取。", elements)
    table = new_table(doc, ["端別", "目前缺少、我們無法自行確認的內容", "補回後用途"], [
        ["Ollama", "正式 200 request／response、model tag／量化、schemaVersion、認證轉送、錯誤碼、LLaVA 實際狀態。", "補齊文字建議契約、前端顯示、Gateway 與端到端 UAT。"],
        ["演算法", "資料／類別／identity 版本、每 fold metrics、final hash、PRO 指標、回饋增量訓練前後結果。", "補齊模型工作流、實驗結果、部署與版本判讀。"],
        ["爬蟲", "來源與規範、欄位 mapping、selector、去重、圖片／色號、最近 run、人工審核。", "補齊商品資料來源、推薦依據與後台上架 UAT。"],
        ["資料庫", "collection schema、會員／商品 API 版本、ID 關聯、權限、索引、備份、錯誤契約與完整 UAT。", "補齊系統架構、資料庫設計、資安與 E2E 驗收。"],
    ], [3.0, 12.0, 4.8], 8.7)
    elements.append(table._tbl)
    new_body(doc, "如果對方尚未完成，請直接標示 BLOCKED、NOT RUN 或 NOT DONE，並寫阻塞原因；不要用本機健康檢查、截圖或猜測資料補成 PASS。四份補件文件位於 `docs/跨端資料補件/`，分別是 Ollama、演算法、爬蟲與資料庫端。", elements)
    body = doc._element.body
    sect_pr = body.sectPr
    for element in elements:
        sect_pr.addprevious(element)


def main():
    create_flowchart_images()
    prepare_algorithm_figures()
    doc = Document(SOURCE)
    configure_doc(doc)
    fix_known_typos(doc)
    replace_figure_image_before_caption(doc, "臉部分析流程圖", USER_FACE_ACTIVITY, 15.5)
    classify_original(doc)
    add_model_history_under_related_tech(doc)
    add_system_data_flow_under_design(doc)
    add_model_worklog_under_implementation(doc)
    figure_entries, table_entries = add_caption_numbering(doc)
    build_cover_and_static_toc(doc, figure_entries, table_entries)
    remove_unnecessary_blank_paragraphs(doc)
    normalize_document_fonts(doc)
    remove_shading_and_force_black(doc)
    reference_pages = grayscale_initial_reference_pages(doc)
    compact_conclusion_spacing(doc)
    # Word 開啟時更新頁碼欄位；目錄本身是預先填好的黑白文字，不是空白 TOC field。
    settings = doc.settings._element
    update = settings.find(qn("w:updateFields"))
    if update is None:
        update = OxmlElement("w:updateFields")
        settings.append(update)
    update.set(qn("w:val"), "true")
    doc.save(OUTPUT)
    check = Document(OUTPUT)
    required = ["臉部分析模型訓練工作流", "UAT 測試工作流", "渲染端的輸入與輸出", "前端與 Gateway 的實際責任邊界", "Ollama 個人化妝容建議模組", "商品推薦演算法與排序流程", "圖目錄", "表目錄", "妝識你的美"]
    for needle in required:
        if not any(needle in p.text for p in check.paragraphs):
            raise RuntimeError(f"輸出缺少：{needle}")
    print(f"OUTPUT={OUTPUT}")
    print(f"PARAGRAPHS={len(check.paragraphs)}")
    print(f"TABLES={len(check.tables)}")
    print(f"UAT_COLUMNS={len(next(t for t in check.tables if t.rows and t.rows[0].cells[0].text == '發現問題').columns)}")
    print("BLACK_WHITE_FORMAT=True")
    print(f"REFERENCE_PAGES_GRAYSCALE={reference_pages}")


if __name__ == "__main__":
    main()
