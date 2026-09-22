from pathlib import Path
import re

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '妝識你的美_最新原稿_20260914.docx'
OUTPUT = ROOT / '妝識你的美_最終排版與分圖版_20260914.docx'
FIGURES = ROOT / 'docs/figures/final_swimlanes_20260914'

doc = Document(SOURCE)

def drop(element):
    element.getparent().remove(element)

def paragraph_starting(text):
    return next(p for p in doc.paragraphs if p.text.strip().startswith(text))

def add_before(anchor, text='', style='Normal'):
    return anchor.insert_paragraph_before(text, style)

def set_black_font(run, heading=False):
    props = run._element.get_or_add_rPr()
    fonts = props.rFonts
    if fonts is None:
        fonts = OxmlElement('w:rFonts')
        props.append(fonts)
    fonts.set(qn('w:ascii'), 'Times New Roman')
    fonts.set(qn('w:hAnsi'), 'Times New Roman')
    fonts.set(qn('w:cs'), 'Times New Roman')
    fonts.set(qn('w:eastAsia'), '標楷體')
    run.font.name = 'Times New Roman'
    run.font.size = Pt(14 if heading else 12)
    run.font.color.rgb = None

# Rebuild all three directories from current headings/captions, so page links
# remain correct after replacing the oversize system figure.
toc_start = paragraph_starting('目錄')._p
# The first "摘要" is an old TOC entry. Use the actual Heading 1 body title.
abstract = next(p for p in doc.paragraphs if p.text.strip() == '摘要' and p.style.name.startswith('Heading'))._p
body = doc.element.body
nodes = list(body)
for node in nodes[nodes.index(toc_start):nodes.index(abstract)]:
    drop(node)

# Replace the unreadable full-system overview (old Figure 3-14) with a linked,
# readable group of five diagrams. Existing Figure 3-15 onward keep their IDs.
old_caption = paragraph_starting('圖 3-14')._p
old_image = old_caption.getprevious()
if old_image is not None and old_image.tag == qn('w:p'):
    drop(old_image)
drop(old_caption)
# The overview image is followed by a separate render-input diagram.  Remove
# only the former; its paragraph is not adjacent to the caption in this file.
for paragraph in list(doc.paragraphs):
    extents = paragraph._p.xpath('.//wp:extent')
    if (not paragraph.text.strip()
            and any(item.get('cx') == '5760000' and item.get('cy') == '3355767'
                    for item in extents)):
        drop(paragraph._p)

# The existing Figure 3-15 image is already immediately before its caption.
# Insert the replacement group before that image, so that Figure 3-15 keeps
# its own image, caption, and explanatory paragraph together.
figure_315_caption = paragraph_starting('圖 3-15')
figure_315_image = figure_315_caption._p.getprevious()
anchor = next(p for p in doc.paragraphs if p._p is figure_315_image)
parts = [
    ('figure_3_14a_auth.png', '圖 3-14（a） 身分驗證與請求分流',
     '本圖說明使用者請求先由前端組裝，再由 Gateway 依登入狀態、訪客額度、路由、HTTP method、CSRF、Origin 與權限檢查後分流。前端不直接持有上游服務憑證；通過檢查後才由 Gateway 代表前端呼叫對應服務。'),
    ('figure_3_14b_face.png', '圖 3-14（b） 臉部分析與結果確認',
     '本圖說明上傳照片後，Face Service 建立非同步 Face Job，依序取得 Face Mesh、裁切 ROI、執行五官模型並整合 analysisPackage。前端以 faceJobId 輪詢結果，使用者可確認或修正顯示內容；修正回饋的保存不等同模型已完成訓練或部署。'),
    ('figure_3_14c_suggestion.png', '圖 3-14（c） 個人化妝容建議',
     '本圖說明建議服務以 analysisPackage、妝容風格與 userNote 組裝請求，經 Gateway 轉送至 Ollama 建議服務。正面影像存在時，LLaVA 僅作視覺補充；Gemma 3 的結構化回應仍須經欄位與 schemaVersion 檢查後才由前端顯示。'),
    ('figure_3_14d_render.png', '圖 3-14（d） 妝容渲染與私人圖片讀取',
     '本圖說明渲染請求經 Gateway 驗證後建立非同步 Render Job，前端以 jobId 輪詢狀態。完成後，Gateway 仍須檢查 owner 與媒體權限，並回傳 Gateway Media Path；前端不直接取得 GCS 的私人媒體路徑。'),
    ('figure_3_14e_recommendation.png', '圖 3-14（e） 商品推薦、收藏與使用者回饋',
     '本圖分別呈現商品推薦、收藏與歷史、使用者回饋三項可獨立觸發的操作。推薦以分析資料與商品條件比對，收藏與歷史依身分權限保存；回饋資料是否可供後續使用，仍取決於同意狀態與後台複核，不能視為模型已訓練。'),
]
for index, (filename, caption, description) in enumerate(parts):
    image_p = add_before(anchor, '')
    image_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    image_p.paragraph_format.page_break_before = True
    image_p.paragraph_format.keep_with_next = True
    image_p.add_run().add_picture(str(FIGURES / filename), width=Inches(5.15))
    caption_p = add_before(anchor, caption)
    caption_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption_p.paragraph_format.keep_with_next = True
    description_p = add_before(anchor, description)
    description_p.paragraph_format.space_after = Pt(6)

# Existing captions must remain paired with their immediately preceding image.
for paragraph in doc.paragraphs:
    if re.match(r'^圖\s*\d+-\d+', paragraph.text.strip()):
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        previous = paragraph._p.getprevious()
        if previous is not None and previous.tag == qn('w:p'):
            image_paragraph = next((p for p in doc.paragraphs if p._p is previous), None)
            if image_paragraph is not None and image_paragraph._p.xpath('.//a:blip'):
                image_paragraph.paragraph_format.keep_with_next = True

# Place table titles above their table and pair captions to the following table.
for paragraph in list(doc.paragraphs):
    if re.match(r'^表\s*\d+-\d+', paragraph.text.strip()):
        node = paragraph._p.getnext()
        while node is not None and node.tag != qn('w:tbl'):
            if node.tag == qn('w:p') and re.match(r'^[圖表]\s*\d+-\d+', ''.join(node.xpath('.//w:t/text()')).strip()):
                break
            node = node.getnext()
        if node is not None and node.tag == qn('w:tbl'):
            node.addprevious(paragraph._p)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.keep_with_next = True

# Normalize page/paragraph behavior but preserve source content and tables.
for paragraph in doc.paragraphs:
    paragraph.paragraph_format.line_spacing = 1
    paragraph.paragraph_format.widow_control = True
    if paragraph.style.name.startswith('Heading'):
        paragraph.paragraph_format.keep_with_next = True
        paragraph.paragraph_format.space_before = Pt(8)
        paragraph.paragraph_format.space_after = Pt(4)
    for run in paragraph.runs:
        set_black_font(run, paragraph.style.name.startswith('Heading'))

for table in doc.tables:
    for row in table.rows:
        tr_pr = row._tr.get_or_add_trPr()
        if tr_pr.find(qn('w:cantSplit')) is None:
            tr_pr.append(OxmlElement('w:cantSplit'))
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.line_spacing = 1
                paragraph.paragraph_format.keep_with_next = False
                for run in paragraph.runs:
                    set_black_font(run, False)
    if table.rows:
        tr_pr = table.rows[0]._tr.get_or_add_trPr()
        if tr_pr.find(qn('w:tblHeader')) is None:
            tr_pr.append(OxmlElement('w:tblHeader'))

# Remove colors, fills, and highlights throughout the document without changing
# the underlying text; apply grayscale only to raster images.
roots = [doc.element, doc.styles.element]
for relationship in doc.part.rels.values():
    if not relationship.is_external and any(token in relationship.reltype for token in ('header', 'footer')):
        roots.append(relationship.target_part.element)
for root in roots:
    for shading in list(root.xpath('.//w:shd | .//w:highlight')):
        drop(shading)
    for color in root.xpath('.//w:color'):
        color.attrib.clear()
        color.set(qn('w:val'), '000000')
    for blip in root.xpath('.//a:blip'):
        if blip.find(qn('a:grayscl')) is None:
            blip.append(OxmlElement('a:grayscl'))

# Recreate static directories with bookmarks and genuine PAGEREF fields, which
# Microsoft Word refreshes before visual QA and when the user edits later.
anchor = next(p for p in doc.paragraphs if p.text.strip() == '摘要' and p.style.name.startswith('Heading'))
headings = [p for p in doc.paragraphs if p.style.name.startswith('Heading')]
captions = [p for p in doc.paragraphs if re.match(r'^[圖表]\s*\d+-\d+', p.text.strip())]
bookmark_id = 13000
def bookmark(paragraph):
    global bookmark_id
    bookmark_id += 1
    name = f'makeup_thesis_{bookmark_id}'
    start = OxmlElement('w:bookmarkStart')
    start.set(qn('w:id'), str(bookmark_id))
    start.set(qn('w:name'), name)
    end = OxmlElement('w:bookmarkEnd')
    end.set(qn('w:id'), str(bookmark_id))
    paragraph._p.insert(1 if paragraph._p.pPr is not None else 0, start)
    paragraph._p.append(end)
    return name

for title, items in [
    ('目錄', headings),
    ('圖目錄', [p for p in captions if p.text.strip().startswith('圖')]),
    ('表目錄', [p for p in captions if p.text.strip().startswith('表')]),
]:
    title_p = add_before(anchor, title)
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_p.paragraph_format.page_break_before = True
    title_p.paragraph_format.keep_with_next = True
    for target in items:
        item = add_before(anchor, re.sub(r'\s+', ' ', target.text).strip() + '\t')
        item.paragraph_format.space_after = Pt(0)
        item.paragraph_format.first_line_indent = Pt(0)
        item.paragraph_format.left_indent = Pt(12 if target.style.name == 'Heading 2' else 24 if target.style.name == 'Heading 3' else 0)
        item.paragraph_format.tab_stops.add_tab_stop(Inches(6.0), 2, 1)
        field = OxmlElement('w:fldSimple')
        field.set(qn('w:instr'), 'PAGEREF ' + bookmark(target) + ' \\h')
        run = OxmlElement('w:r')
        text = OxmlElement('w:t')
        text.text = '0'
        run.append(text)
        field.append(run)
        item._p.append(field)

anchor.paragraph_format.page_break_before = True
settings = doc.settings.element
update = OxmlElement('w:updateFields')
update.set(qn('w:val'), 'true')
settings.append(update)
doc.save(OUTPUT)
print(OUTPUT)
print('figures', len([p for p in doc.paragraphs if re.match(r'^圖\s*\d+-\d+', p.text.strip())]))
print('tables', len(doc.tables))
