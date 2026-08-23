from pathlib import Path
import xml.etree.ElementTree as ET

import os

# 輸出路徑先前寫死成某台機器的絕對路徑，換機器就跑不起來。
OUT = Path(os.getenv("WIREFRAME_OUTPUT",
                     Path(__file__).resolve().parent / "DecorateMe_第四章介面示意圖_黑白標準版.drawio"))

# agent 是 drawio 檔頭記錄「這個檔是誰產生的」的欄位，填產生它的腳本比填工具名有用。
mxfile = ET.Element("mxfile", host="app.diagrams.net", modified="2026-07-21T00:00:00.000Z",
                    agent="build_drawio_wireframes.py", version="24.7.17", type="device", compressed="false")

STYLE = {
    "box": "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;fontColor=#000000;fontSize=12;align=center;verticalAlign=middle;strokeWidth=1;",
    "head": "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;fontColor=#000000;fontSize=14;fontStyle=1;align=center;verticalAlign=middle;strokeWidth=1.5;",
    "text": "text;html=1;strokeColor=none;fillColor=none;fontColor=#000000;fontSize=12;align=left;verticalAlign=middle;whiteSpace=wrap;",
    "center": "text;html=1;strokeColor=none;fillColor=none;fontColor=#000000;fontSize=12;align=center;verticalAlign=middle;whiteSpace=wrap;",
    "button": "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;fontColor=#000000;fontSize=12;fontStyle=1;align=center;verticalAlign=middle;strokeWidth=1.5;",
    "dashed": "rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;fontColor=#000000;fontSize=12;align=center;verticalAlign=middle;strokeWidth=1;dashed=1;",
    "diamond": "rhombus;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#000000;fontColor=#000000;fontSize=12;align=center;verticalAlign=middle;strokeWidth=1.5;",
    "edge": "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeColor=#000000;strokeWidth=1.5;endArrow=block;endFill=1;fontColor=#000000;fontSize=11;",
}


class Page:
    def __init__(self, name, title):
        diagram = ET.SubElement(mxfile, "diagram", id=f"page-{len(mxfile)+1}", name=name)
        self.model = ET.SubElement(diagram, "mxGraphModel", dx="1169", dy="827", grid="1", gridSize="10", guides="1", tooltips="1", connect="1", arrows="1", fold="1", page="1", pageScale="1", pageWidth="1169", pageHeight="827", math="0", shadow="0")
        self.root = ET.SubElement(self.model, "root")
        ET.SubElement(self.root, "mxCell", id="0")
        ET.SubElement(self.root, "mxCell", id="1", parent="0")
        self.n = 2
        self.box(30, 20, 1109, 50, title, "head")

    def box(self, x, y, w, h, value="", style="box", parent="1"):
        i = str(self.n); self.n += 1
        c = ET.SubElement(self.root, "mxCell", id=i, value=value, style=STYLE[style], vertex="1", parent=parent)
        ET.SubElement(c, "mxGeometry", x=str(x), y=str(y), width=str(w), height=str(h), **{"as": "geometry"})
        return i

    def line(self, source, target, value=""):
        i = str(self.n); self.n += 1
        c = ET.SubElement(self.root, "mxCell", id=i, value=value, style=STYLE["edge"], edge="1", parent="1", source=source, target=target)
        ET.SubElement(c, "mxGeometry", relative="1", **{"as": "geometry"})
        return i

    def browser(self, page_name):
        self.box(70, 90, 1029, 660, "", "box")
        self.box(70, 90, 1029, 42, "Decorate Me　｜　" + page_name + "　　　　　　　　　　　　　　　　　會員中心　登出", "head")
        self.box(70, 132, 190, 618, "臉部分析\n\n妝容風格\n\n妝容建議\n\n商品推薦\n\n分析紀錄\n\n妝容對比圖\n\n購物車", "text")
        return (280, 152, 799, 578)


# 操作總流程
p = Page("操作總流程", "Decorate Me 使用者介面與操作流程（圖4-1至圖4-10）")
steps = [
    "圖4-1\n會員登入／註冊", "圖4-2\n選擇BASIC／PRO", "圖4-3\n上傳或拍攝照片",
    "圖4-4\n臉部分析結果", "圖4-5\n選擇妝容風格", "圖4-6\nOllama妝容建議",
    "圖4-7\nAI妝容渲染", "圖4-8\n妝前妝後對比／收藏", "圖4-9\n個人化商品推薦", "圖4-10\n購物車／個人紀錄"
]
ids=[]
for idx, label in enumerate(steps):
    col=idx%5; row=idx//5
    x=55+col*222; y=160+row*300
    ids.append(p.box(x,y,170,90,label,"box"))
for i in range(4): p.line(ids[i],ids[i+1])
p.line(ids[4],ids[5])
for i in range(5,9): p.line(ids[i],ids[i+1])
p.box(55, 690, 1059, 45, "標準流程：身分驗證 → 臉部分析 → 妝容建議 → 影像渲染 → 商品導購與紀錄管理", "dashed")

# 4-1
p=Page("圖4-1", "圖4-1　系統登入與會員註冊畫面")
p.box(310,120,550,560,"","box")
p.box(310,120,550,60,"Decorate Me　會員入口","head")
p.box(370,215,430,45,"電子郵件","text"); p.box(370,260,430,45,"請輸入電子郵件","box")
p.box(370,325,430,45,"密碼","text"); p.box(370,370,430,45,"請輸入密碼","box")
p.box(370,455,205,50,"登入","button"); p.box(595,455,205,50,"註冊新會員","button")
p.box(370,540,430,70,"登入成功後進入主系統；工作階段由JWT與安全Cookie驗證。","dashed")

# 4-2
p=Page("圖4-2", "圖4-2　BASIC／PRO臉部分析模式選擇畫面")
x,y,w,h=p.browser("臉部分析模式")
p.box(310,175,350,360,"BASIC模式\n\n適用對象：一般使用者／訪客\n照片需求：一張清楚正面照\n分析內容：正面五官、膚色與輪廓\n用途：快速分析及妝容推薦","box")
p.box(700,175,350,360,"PRO模式\n\n適用對象：VIP會員\n照片需求：正面照＋側面輔助照\n分析內容：完整BASIC結果＋雙角度膚色輔助\n限制：側面深度特徵仍為未來擴充","box")
p.box(395,565,180,50,"選擇BASIC","button"); p.box(785,565,180,50,"選擇PRO","button")

# 4-3
p=Page("圖4-3", "圖4-3　照片上傳或相機拍攝畫面")
x,y,w,h=p.browser("照片輸入")
p.box(330,180,430,330,"拖曳照片至此處\n或按下「選擇圖片」\n\n［正面人臉取景框］\n\n支援有效圖片格式\n預設上限：8 MB／1,600萬像素","dashed")
p.box(790,180,240,70,"拍攝指引\n正面、自然表情、均勻光線","box")
p.box(790,270,240,70,"避免事項\n遮擋、濾鏡、濃妝、過大偏角","box")
p.box(790,390,240,50,"開啟相機","button"); p.box(790,465,240,50,"選擇圖片","button")
p.box(560,555,240,55,"送出臉部分析","button")

# 4-4
p=Page("圖4-4", "圖4-4　臉部分析結果畫面")
x,y,w,h=p.browser("臉部分析結果")
p.box(315,175,260,290,"［使用者照片］\n\n姿態檢查：通過\n分析版本：BASIC／PRO","box")
labels=["臉型：＿＿＿＿","眉型：＿＿＿＿","眼型：＿＿＿＿","鼻型：＿＿＿＿","唇型：＿＿＿＿","膚色：＿＿＿＿","LAB：L＿＿ a＿＿ b＿＿"]
for i,t in enumerate(labels): p.box(615,175+i*55,390,42,t,"box")
p.box(420,605,240,50,"重新分析","button"); p.box(710,605,240,50,"選擇妝容風格","button")

# 4-5
p=Page("圖4-5", "圖4-5　妝容風格選擇畫面")
x,y,w,h=p.browser("妝容風格")
styles=["韓系清透","日系透明感","港風","千金感","Soft Baddie","病嬌風","男士自然妝"]
for i,t in enumerate(styles):
    col=i%4; row=i//4
    p.box(310+col*185,175+row*210,160,165,"［風格預覽］\n\n"+t,"box")
p.box(565,610,260,50,"確認所選妝容風格","button")

# 4-6
p=Page("圖4-6", "圖4-6　Ollama個人化妝容建議畫面")
x,y,w,h=p.browser("個人化妝容建議")
p.box(310,175,740,60,"分析摘要：臉型／眉型／眼型／鼻型／唇型／膚色　｜　目標風格：＿＿＿＿","box")
sections=["底妝：依膚色與風格調整質感及遮瑕方式","眉妝：依眉型提供填補、眉峰與眉尾建議","眼妝：說明眼影層次、眼線方向與睫毛重點","腮紅／修容：依臉型說明位置、方向與範圍","唇妝：依唇型與風格提供質地及塗抹方式"]
for i,t in enumerate(sections): p.box(310,260+i*68,740,52,t,"box")
p.box(550,625,260,50,"產生AI妝容渲染","button")

# 4-7
p=Page("圖4-7", "圖4-7　AI妝容渲染進度與結果畫面")
x,y,w,h=p.browser("AI妝容渲染")
p.box(325,180,310,360,"［原始照片］\n\n工作編號：＿＿＿＿\n風格：＿＿＿＿","box")
p.box(680,180,355,360,"［渲染結果／處理中］\n\n狀態：等待中／處理中／完成／失敗\n\n處理進度：＿＿＿＿","dashed")
p.box(400,590,220,50,"取消／返回","button"); p.box(730,590,220,50,"查看妝前妝後對比","button")

# 4-8
p=Page("圖4-8", "圖4-8　妝前妝後對比與收藏畫面")
x,y,w,h=p.browser("妝容對比圖")
p.box(310,175,335,380,"妝前\n\n［原始照片］","box")
p.box(700,175,335,380,"妝後\n\n［AI渲染圖片］","box")
p.box(430,595,210,50,"返回風格選擇","button"); p.box(705,595,210,50,"收藏此妝容對比","button")

# 4-9
p=Page("圖4-9", "圖4-9　個人化商品推薦畫面")
x,y,w,h=p.browser("商品推薦")
p.box(310,165,740,55,"推薦條件：膚色＿＿　唇色LAB＿＿　妝容風格＿＿　｜　排序：適配程度","box")
for i in range(6):
    col=i%3; row=i//3
    p.box(310+col*250,250+row*185,220,155,f"［商品圖片］\n商品名稱 {i+1}\n類別／色系／價格\n適配原因\n［加入購物車］","box")

# 4-10
p=Page("圖4-10", "圖4-10　購物車與個人紀錄畫面")
x,y,w,h=p.browser("購物車／個人紀錄")
p.box(310,170,740,55,"頁籤：購物車　｜　分析紀錄　｜　收藏妝容　｜　會員資料","head")
p.box(310,250,740,65,"商品／紀錄項目　　　　　　　　　數量／日期　　　　狀態　　　　操作","box")
for i in range(4): p.box(310,315+i*70,740,55,f"項目 {i+1}　　　　　　　　　　　　　＿＿＿＿　　　　　＿＿＿＿　　　查看／移除","box")
p.box(790,625,260,50,"確認購物車／查看紀錄","button")

tree = ET.ElementTree(mxfile)
ET.indent(tree, space="  ")
OUT.parent.mkdir(parents=True, exist_ok=True)
tree.write(OUT, encoding="utf-8", xml_declaration=True)
print(OUT)

