from pathlib import Path
from zipfile import ZipFile
import os
import re

from docx import Document

# 跟 build_proposal_docx.py 用同一組路徑設定：兩支腳本讀寫的是同一份稿件與同一份輸出，
# 各自寫死一份絕對路徑的話，改一邊忘了改另一邊就會安靜地比對到不相干的檔案。
ROOT = Path(__file__).resolve().parent
source_path = Path(os.getenv("PROPOSAL_SOURCE", ROOT / "docs" / "proposal_source.txt"))
docx_path = Path(os.getenv("PROPOSAL_OUTPUT", ROOT / "2026臺灣數創大賞_裝識你的美_補足版.docx"))

source_lines = [line.strip() for line in source_path.read_text(encoding="utf-8").splitlines() if line.strip()]
doc = Document(docx_path)
doc_lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

cursor = 0
missing = []
for line in source_lines:
    try:
        cursor = doc_lines.index(line, cursor) + 1
    except ValueError:
        missing.append(line)

required_insertions = [
    "臉部偵測與姿態判斷",
    "個人化商品推薦",
    "身分驗證與資料安全",
    "使用者操作流程如下:",
    "系統環境需求與限制",
    "使用者介面示意圖說明",
    "建議檢附資料如下:",
]
missing_insertions = [item for item in required_insertions if item not in doc_lines]

with ZipFile(docx_path) as zf:
    document_xml = zf.read("word/document.xml").decode("utf-8")

font_runs = re.findall(r"<w:rFonts[^>]*/>", document_xml)
font_ok = all('w:ascii="Times New Roman"' in tag and 'w:eastAsia="DFKai-SB"' in tag for tag in font_runs)
sizes = re.findall(r'<w:sz w:val="(\d+)"', document_xml)
size_ok = bool(sizes) and all(size == "24" for size in sizes)

print(f"SOURCE_NONBLANK={len(source_lines)}")
print(f"DOC_PARAGRAPHS={len(doc_lines)}")
print(f"MISSING_SOURCE={len(missing)}")
print(f"MISSING_INSERTIONS={len(missing_insertions)}")
print(f"FONT_RUNS={len(font_runs)} FONT_OK={font_ok}")
print(f"SIZE_TAGS={len(sizes)} SIZE_12PT_OK={size_ok}")
if missing:
    print("MISSING_SOURCE_LINES:")
    print("\n".join(missing))
if missing_insertions:
    print("MISSING_INSERTIONS_LIST:")
    print("\n".join(missing_insertions))

if missing or missing_insertions or not font_ok or not size_ok:
    raise SystemExit(1)
