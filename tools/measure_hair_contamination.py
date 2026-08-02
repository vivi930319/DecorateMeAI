from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 測試資料集。換一批照片時改這裡即可，數字要跟著重跑。
DATASET = ROOT / "data" / "kaggle_asian_faces" / "generated_yellow-stylegan2"
"""量測頭髮遮擋對膚色的污染，並驗證紋理過濾與可信度標記的效果。

Face_analyzer_BASIC 的 SKIN_TEXTURE_STD_MAX / SKIN_SPREAD_UNRELIABLE 註解裡
引用的數字就出自這支腳本。改動那兩個常數前請重跑一次。

做法：把每張照片自己的頭髮（髮際線上方的真實像素）移植到臉頰，
再比對膚色 LAB 與未遮擋時的差距。
"""
import glob
import numpy as np
import cv2

from Face_analyzer_BASIC import FaceAnalyzer
from analysis_package import normalize_face_analysis

CHEEK_L = [50, 101, 118, 117, 123, 205, 187, 147, 177, 137]

def hair_patch(fa):
    top, chin = fa._pt(10), fa._pt(152); fh = abs(chin[1]-top[1])
    y1,y2 = max(0,int(top[1]-fh*0.28)), max(0,int(top[1]-fh*0.06))
    x1,x2 = max(0,int(top[0]-fh*0.22)), min(fa.w,int(top[0]+fh*0.22))
    return fa.frame[y1:y2, x1:x2].copy() if (y2-y1>=12 and x2-x1>=12) else None

def transplant(fa, patch, cov):
    out = fa.frame.copy()
    hull = cv2.convexHull(np.array([fa._pt(i) for i in CHEEK_L], np.int32))
    x,y,w,h = cv2.boundingRect(hull)
    band = np.zeros(out.shape[:2], np.uint8); cv2.rectangle(band,(x,0),(x+max(2,int(w*cov)),y+h),255,-1)
    cheek = np.zeros(out.shape[:2], np.uint8); cv2.fillConvexPoly(cheek, hull, 255)
    area = cv2.bitwise_and(band, cheek)
    t = np.tile(patch,(out.shape[0]//patch.shape[0]+1, out.shape[1]//patch.shape[1]+1,1))[:out.shape[0],:out.shape[1]]
    out[area>0] = t[area>0]
    return out

imgs = sorted(glob.glob(str(DATASET / "*.png")))[:40]
clean_flagged = clean_n = 0
occ_flagged = occ_n = 0
dEs, flagged_dEs, unflagged_dEs = [], [], []
sample_json = None

for path in imgs:
    try:
        fa = FaceAnalyzer(path, strict_angle=False, require_insight=False)
        patch = hair_patch(fa)
        if patch is None: continue
        base = fa.get_skin_color()
        rel0 = fa.skin_reliability
        L0, a0, b0 = base[5], base[6], base[7]
        if cv2.cvtColor(patch, cv2.COLOR_BGR2Lab)[:,:,0].mean()/2.55 > L0-8: continue
    except Exception:
        continue
    clean_n += 1
    if not rel0["reliable"]: clean_flagged += 1
    if sample_json is None:
        sample_json = normalize_face_analysis(fa.export_json())

    for cov in (0.3, 0.45, 0.6, 0.75):
        fa2 = FaceAnalyzer(path, strict_angle=False, require_insight=False)
        fa2.frame = transplant(fa, patch, cov)
        try:
            r = fa2.get_skin_color()
        except Exception:
            continue
        dE = ((r[5]-L0)**2 + (r[6]-a0)**2 + (r[7]-b0)**2) ** 0.5
        occ_n += 1; dEs.append(dE)
        if not fa2.skin_reliability["reliable"]:
            occ_flagged += 1; flagged_dEs.append(dE)
        else:
            unflagged_dEs.append(dE)

print(f"\n=== 修正後（真實程式碼路徑）===")
print(f"乾淨照片 {clean_n} 張、遮蔽案例 {occ_n} 組\n")
print(f"誤報率（乾淨照片被標成不可信）: {100*clean_flagged/max(1,clean_n):.0f}%   ({clean_flagged}/{clean_n})")
print(f"偵測率（遮蔽案例被標成不可信）: {100*occ_flagged/max(1,occ_n):.0f}%   ({occ_flagged}/{occ_n})")
print(f"\n膚色誤差：平均 ΔE {np.mean(dEs):.2f}   最差 {max(dEs):.2f}   ΔE>5 佔 {100*np.mean([d>5 for d in dEs]):.0f}%")
if unflagged_dEs:
    print(f"  被標成『可信』的那些案例：最差 ΔE {max(unflagged_dEs):.2f}   ΔE>5 佔 {100*np.mean([d>5 for d in unflagged_dEs]):.0f}%")
if flagged_dEs:
    print(f"  被標成『不可信』的那些案例：最差 ΔE {max(flagged_dEs):.2f}")

print(f"\n=== analysis_package 輸出（給推薦端的欄位）===")
st = sample_json["skinTone"]
print(f"  labReliable   = {st['labReliable']}")
print(f"  labReliability= {st['labReliability']}")
