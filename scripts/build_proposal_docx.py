from pathlib import Path
import os
import re

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt


# 兩條路徑先前都寫死成某台機器上的絕對路徑，其中來源檔還指向一個臨時附件資料夾——
# 換一台機器、或那個資料夾被清掉，這支腳本就再也跑不起來，而且錯誤訊息只會說找不到檔案。
# 改成專案相對路徑，並允許用環境變數覆寫。
ROOT = Path(__file__).resolve().parent
SOURCE = Path(os.getenv("PROPOSAL_SOURCE", ROOT / "docs" / "proposal_source.txt"))
OUTPUT = Path(os.getenv("PROPOSAL_OUTPUT", ROOT / "2026臺灣數創大賞_裝識你的美_補足版.docx"))

TECH_INSERT = """臉部偵測與姿態判斷
系統使用OpenCV解碼圖片，並設定檔案大小、總像素與影像尺寸上限，避免異常檔案占用伺服器資源。接著由InsightFace偵測主要人臉並估計yaw、pitch及roll頭部姿態；BASIC正面分析會檢查照片角度是否符合要求，降低側臉透視變形對五官比例判斷的影響。通過檢查後，再由MediaPipe Face Mesh取得臉部輪廓、眉毛、眼睛、鼻子、嘴唇及下巴等密集關鍵點。
影像前處理與ROI擷取
照片會依分析需求進行BGR與RGB色彩轉換、尺寸調整、亮度判斷及ImageNet正規化。系統依MediaPipe關鍵點分別裁切臉型、眉型、眼型、鼻型與唇型的感興趣區域（ROI），使模型集中判斷指定部位，降低背景、服裝及髮型干擾。訓練資料與線上推論共用相同ROI定義，避免裁切範圍不一致造成模型表現下降。
臉部特徵分類模型
系統曾以相同資料、相同MediaPipe ROI、相同seed 42及相同5-fold交叉驗證，比較規則式分析、基礎CNN、MobileNetV3-small及DINOv2 ViT-S/14。評估採用Macro Accuracy，使每個類別的召回率具有相同權重，避免多數類別掩蓋少數類別的錯誤。實驗顯示不同五官適合不同模型，因此採分區辨識與分模型部署，而非以單一模型處理全部特徵。
MobileNetV3-small使用ImageNet預訓練權重進行微調，並匯出為ONNX格式，由ONNX Runtime在Cloud Run的CPU環境執行。DINOv2則將224×224的ROI轉換為384維影像特徵，再交由Linear SVM或Logistic Regression分類。為降低雲端映像大小及冷啟動時間，DINOv2 ViT-S/14骨幹已離線匯出為ONNX，正式服務不需安裝完整PyTorch。
目前DINOv2針對臉型、眼型與鼻型先採Shadow模式部署，背景記錄其與現行正式模型的差異，但預設不直接取代使用者看到的答案。若模型載入、ROI裁切或單一部位推論失敗，系統會保留既有分析結果，使單一模型錯誤不致中斷完整服務。
膚色、唇色與臉部對稱性分析
系統依臉部關鍵點建立皮膚遮罩，從臉頰等代表性區域擷取色彩，並避開眼睛、眉毛、嘴唇、頭髮及背景。分析採用CIE LAB色彩空間，其中L代表明暗、a代表綠紅方向、b代表藍黃方向，再整理為膚色明度、四季型傾向及嘴唇LAB數值，作為底妝、腮紅、眼影、唇彩及商品推薦的參考。PRO模式可將正面照與輕微側面照的LAB結果平均，以降低單一角度局部光線造成的偏差；目前側面照主要用於膚色輔助，完整側面鼻型分析仍列為未來擴充功能。
本地大型語言模型與提示詞工程
系統將臉型、眉型、眼型、鼻型、唇型、膚色與使用者選擇的妝容風格轉換為結構化資料，再交由Ollama本地大型語言模型產生繁體中文建議。提示詞內建各妝容風格的色彩、底妝、眉妝、眼妝、腮紅、修容及唇妝規則，並限制模型不得捏造品牌、商品色號或未經分析的臉部特徵。Ollama同時產生供影像模型使用的英文渲染指令；若語言模型暫時無法使用，系統可退回預設風格規則，避免流程完全中斷。
AI影像渲染
Render Service依原始照片、臉部分析摘要、妝容風格及Ollama產生的個人化英文提示詞呼叫生成式影像服務。提示詞加入身分保留限制，要求模型保留原始臉型、五官比例、膚色、肌膚紋理、髮型、表情、姿勢、服裝、背景、光線與構圖，只調整底妝、眉妝、眼妝、腮紅、修容及唇妝。渲染採非同步工作模式，前端以工作編號查詢處理狀態，完成後再顯示妝前與妝後對比圖。
個人化商品推薦
商品推薦會整合使用者膚色、唇色LAB數值、臉部分析結果及所選妝容風格，將商品色彩與使用者特徵進行條件式比對，再依適配程度產生個人化排序。推薦結果與商品資料庫、會員收藏及購物車串接，使使用者能從妝容分析直接進入商品瀏覽與購買流程。
系統架構與雲端技術
系統採前後端分離及服務模組化設計，主要元件如下:
Firebase Hosting：提供網站前端、操作介面及靜態資源。
AI Gateway：統一處理會員驗證、權限檢查、API請求轉送及內部服務保護。
Face BASIC/Face PRO：執行正面照片及多角度輔助臉部分析。
Ollama Suggestion：產生個人化妝容文字建議及影像渲染提示詞。
Render Service：呼叫生成式影像模型並管理非同步渲染工作。
Firestore：儲存分析及渲染工作的狀態與結果，使多個Cloud Run執行個體可共用資料。
Google Cloud Storage：依temporary及retained路徑管理暫存與會員保留影像。
Cloud Run：部署AI Gateway、臉部分析及渲染等可獨立擴充的後端服務。
身分驗證與資料安全
會員登入成功後，AI Gateway會簽發具有期限的JWT Access Token，支援Authorization: Bearer <token>，並搭配HttpOnly、Secure及SameSite Cookie管理瀏覽器工作階段。Gateway呼叫Cloud Run私有服務時，另使用IAM Identity Token及服務端API Key進行服務間驗證。分析工作與渲染影像皆綁定不直接揭露會員信箱的擁有者識別碼，使用者必須通過會員身分及所有權檢查後才能取得結果。"""

OPERATION_INSERT = """操作方法
使用者操作流程如下:
會員登入：使用者進入Decorate Me網站後，可註冊會員或使用既有帳號登入；登入成功後，才能使用個人化分析、收藏及歷史紀錄等功能。
選擇分析模式：一般使用者可選擇BASIC模式上傳或拍攝一張正面照片；符合會員資格的使用者可選擇PRO模式，依畫面指示提供正面照與側面輔助照片。
提供臉部照片：照片應包含一張清楚完整的主要人臉，正面面對鏡頭、表情自然、光線均勻，並避免口罩、瀏海、手部、濃妝或濾鏡遮擋五官。
執行臉部分析：系統檢查圖片格式、大小、人臉及頭部角度後，顯示臉型、眉型、眼型、鼻型、唇型、膚色與其他可用分析結果。
選擇妝容風格：使用者可選擇韓系清透、日系透明感、港風、千金感、Soft Baddie、病嬌風或男士自然妝等風格。
取得妝容建議：系統將臉部分析與所選風格交由Ollama處理，顯示底妝、眉妝、眼妝、腮紅、修容及唇妝等個人化建議。
產生妝容渲染：使用者按下渲染按鈕後，系統建立影像生成工作並顯示處理狀態；完成後即可查看妝後模擬圖。
查看前後對比：使用者可並列查看原始照片與AI渲染結果，並將喜歡的妝容對比圖加入收藏，作為日後參考。
查看推薦商品：使用者可依膚色、唇色LAB數值及妝容風格查看推薦商品，並將商品加入購物車。
查詢個人紀錄：使用者可從分析紀錄、妝容建議、收藏及購物車頁面查看個人資料；操作完成後可按下登出結束工作階段。
系統環境需求與限制
使用者端環境需求如下:
裝置需求：桌上型電腦、筆記型電腦、平板或智慧型手機。
瀏覽器需求：建議使用最新版Google Chrome、Microsoft Edge、Safari或Firefox，並開啟JavaScript與Cookie。
網路需求：臉部分析及AI影像渲染需連接網際網路，建議使用穩定的Wi-Fi、5G或有線網路。
相機需求：如使用即時拍攝功能，裝置需具備可用相機，並授權瀏覽器存取相機。
照片需求：照片需包含清楚、完整且主要的單一人臉，避免模糊、逆光、過暗、過亮、側臉角度過大及五官遮擋。
系統使用限制如下:
影像限制：單張圖片預設不得超過8 MB或1,600萬像素；不符合格式、無法解碼或超過限制的圖片會被拒絕。
辨識限制：拍攝角度、相機白平衡、光線、濾鏡、濃妝及照片解析度均可能影響五官與膚色分析結果。
PRO模式限制：膚色一律只採正面照（側面照的臉頰取樣無法做遮擋檢查）；側面照用於側臉鼻型輔助分類，臉部深度分析仍屬未來擴充項目。
渲染限制：生成式AI具有隨機性，可能產生局部不自然、色彩差異或臉部細節變化，渲染圖僅供妝容風格預覽。
建議限制：AI妝容建議及商品推薦屬輔助資訊，不取代彩妝師、皮膚科醫師或其他專業人員的判斷。
隱私限制：使用者應取得照片中人物同意，不應上傳未經授權的他人照片；操作後應妥善登出共用裝置。
使用者介面示意圖說明
系統介面示意圖可依下列順序放置:
圖4-1 系統登入與會員註冊畫面：說明會員登入、註冊及進入系統的方式。
圖4-2 BASIC/PRO分析模式選擇畫面：說明一般分析與進階分析的使用資格及照片需求。
圖4-3 照片上傳或相機拍攝畫面：說明照片選取、拍攝指引及送出分析按鈕。
圖4-4 臉部分析結果畫面：呈現臉型、眉型、眼型、鼻型、唇型及膚色結果。
圖4-5 妝容風格選擇畫面：呈現系統提供的多種妝容風格及預覽圖片。
圖4-6 Ollama個人化妝容建議畫面：呈現底妝、眼妝、眉妝、腮紅、修容及唇妝說明。
圖4-7 AI妝容渲染進度與結果畫面：呈現工作處理狀態及完成後的妝容圖片。
圖4-8 妝前妝後對比與收藏畫面：並列顯示原始照片與渲染圖片，並說明收藏功能。
圖4-9 個人化商品推薦畫面：呈現依膚色、唇色與風格推薦的相關商品。
圖4-10 購物車與個人紀錄畫面：說明商品管理、分析紀錄及會員資料查詢方式。"""

ATTACHMENT_INSERT = """建議檢附資料如下:
系統前端操作畫面及主要功能截圖。
BASIC/PRO臉部分析結果範例。
Ollama個人化妝容建議範例。
妝前妝後AI渲染對比圖。
商品推薦、購物車、會員及後臺管理畫面。
系統架構圖及資料流程圖。
模型訓練、5-fold交叉驗證及三模型公平比較結果。
DINOv2 Shadow部署與Cloud Run服務驗證紀錄。
作品展示影片、簡報或線上系統連結。
GitHub原始碼與技術文件連結。"""


def set_run_font(run, bold=None):
    run.font.name = "Times New Roman"
    run.font.size = Pt(12)
    if bold is not None:
        run.bold = bold
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.rFonts
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    rfonts.set(qn("w:ascii"), "Times New Roman")
    rfonts.set(qn("w:hAnsi"), "Times New Roman")
    rfonts.set(qn("w:eastAsia"), "DFKai-SB")
    rfonts.set(qn("w:cs"), "Times New Roman")


def configure_paragraph(p, first_line=True, align=WD_ALIGN_PARAGRAPH.JUSTIFY):
    pf = p.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.keep_together = False
    p.alignment = align
    if first_line:
        pf.first_line_indent = Pt(24)


def add_para(doc, text, kind="body"):
    p = doc.add_paragraph()
    is_heading = kind in {"chapter", "section", "label"}
    is_item = kind == "item"
    configure_paragraph(p, first_line=(kind == "body"), align=(WD_ALIGN_PARAGRAPH.LEFT if is_heading or is_item else WD_ALIGN_PARAGRAPH.JUSTIFY))
    if kind == "chapter":
        p.paragraph_format.page_break_before = True
        p.paragraph_format.keep_with_next = True
    elif kind in {"section", "label"}:
        p.paragraph_format.keep_with_next = True
    elif is_item:
        p.paragraph_format.left_indent = Pt(24)
        p.paragraph_format.first_line_indent = Pt(-24)
    r = p.add_run(text)
    set_run_font(r, bold=is_heading)
    return p


def classify(text):
    s = text.strip()
    if re.match(r"^第[一二三四五六七八九十]+章", s):
        return "chapter"
    if s in {"作品橫跨領域項目", "作品應用類型與範圍", "特性與設計重點", "應用專業技術說明", "創意及原創性說明", "市場潛力說明", "操作方法", "系統環境需求與限制", "使用者介面示意圖說明"}:
        return "section"
    labels = (
        "本作品涵蓋領域如下:", "目標使用者:", "本系統分為六個特性與設計重點如下:",
        "個人化臉部分析:", "個人化妝容文字建議", "多元妝容風格選擇", "妝容渲染效果預覽對比",
        "將本系統獨有的分析、建議和商業化的平台做結合", "隱私與服務安全",
        "對消費者的價值:", "對業者的價值:", "未來商業模式:", "使用者操作流程如下:",
        "使用者端環境需求如下:", "系統使用限制如下:", "系統介面示意圖可依下列順序放置:",
        "建議檢附資料如下:", "臉部偵測與姿態判斷", "影像前處理與ROI擷取", "臉部特徵分類模型",
        "膚色、唇色與臉部對稱性分析", "本地大型語言模型與提示詞工程", "AI影像渲染",
        "個人化商品推薦", "系統架構與雲端技術", "身分驗證與資料安全"
    )
    if s in labels:
        return "label"
    item_prefixes = (
        "美妝造型領域：", "電子商務領域：", "AI 影像辨識領域：", "本地大型語言模型領域：",
        "生成式 AI 影像領域：", "雲端系統與資料管理領域：", "BASIC模式:", "PRO模式:",
        "會員登入：", "選擇分析模式：", "提供臉部照片：", "執行臉部分析：", "選擇妝容風格：",
        "取得妝容建議：", "產生妝容渲染：", "查看前後對比：", "查看推薦商品：", "查詢個人紀錄：",
        "裝置需求：", "瀏覽器需求：", "網路需求：", "相機需求：", "照片需求：", "影像限制：", "辨識限制：",
        "PRO模式限制：", "渲染限制：", "建議限制：", "隱私限制：", "Firebase Hosting：", "AI Gateway：",
        "Face BASIC/Face PRO：", "Ollama Suggestion：", "Render Service：", "Firestore：", "Google Cloud Storage：", "Cloud Run：",
        "圖4-"
    )
    if s.startswith(item_prefixes):
        return "item"
    exact_items = {
        "不熟悉自身臉部特徵及妝容的初學者", "希望嘗試不同妝容的使用者",
        "希望能夠透過試用妝容有方便購買渠道的使用者", "降低嘗試新妝容的門檻。",
        "快速了解自身臉部特徵。", "在購買商品前預覽整體風格。", "取得較具個人化的化妝步驟。",
        "減少因選錯色彩或風格而產生的購買失誤。", "提升網站互動性及使用者停留時間。",
        "提供個人化商品推薦，增加商品曝光機會。", "將妝容風格直接連結至相關商品組合。",
        "取得匿名化的風格偏好資料，作為行銷與選品參考。", "可作為品牌官網、電商平台或實體櫃位的數位美妝顧問。",
        "系統前端操作畫面及主要功能截圖。", "BASIC/PRO臉部分析結果範例。",
        "Ollama個人化妝容建議範例。", "妝前妝後AI渲染對比圖。",
        "商品推薦、購物車、會員及後臺管理畫面。", "系統架構圖及資料流程圖。",
        "模型訓練、5-fold交叉驗證及三模型公平比較結果。", "DINOv2 Shadow部署與Cloud Run服務驗證紀錄。",
        "作品展示影片、簡報或線上系統連結。", "GitHub原始碼與技術文件連結。",
    }
    if s in exact_items:
        return "item"
    return "body"


def add_block(doc, block):
    for line in block.splitlines():
        add_para(doc, line, classify(line))


def main():
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(2.54)
    section.right_margin = Cm(2.54)
    section.header_distance = Cm(1.27)
    section.footer_distance = Cm(1.27)

    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "DFKai-SB")

    for idx, raw in enumerate(lines):
        line = raw.rstrip()
        stripped = line.strip()
        if stripped == "創意及原創性說明":
            add_block(doc, TECH_INSERT)
        if stripped.startswith("第五章"):
            add_block(doc, OPERATION_INSERT)
        if stripped.startswith("github 連結:"):
            add_block(doc, ATTACHMENT_INSERT)

        if not stripped:
            # Preserve the cover's deliberate vertical spacing, but collapse other blank runs.
            if idx < 19:
                add_para(doc, "", "body")
            continue

        if idx < 19:
            p = add_para(doc, stripped, "body")
            p.paragraph_format.first_line_indent = Pt(0)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in p.runs:
                set_run_font(run, bold=False)
            continue

        add_para(doc, stripped, classify(stripped))

    # The source already contains the chapter heading before the inserted Chapter 4 text.
    # Avoid an unnecessary blank first page and add simple centered page numbers.
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    frun = footer.add_run()
    frun._r.append(fld_begin)
    frun._r.append(instr)
    frun._r.append(fld_end)
    set_run_font(frun)

    # Keep all existing and inserted content at the requested 12 pt.
    for p in doc.paragraphs:
        for run in p.runs:
            set_run_font(run, bold=run.bold)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    main()
