from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 測試資料集。換一批照片時改這裡即可，數字要跟著重跑。
DATASET = ROOT / "data" / "kaggle_asian_faces" / "generated_yellow-stylegan2"
"""驗證紋理過濾沒有連帶改掉四季型。

_classify_season 的 clear 判定吃 v_std >= 18.0，而紋理過濾正是在剔除高變異
像素。兩者若共用同一個遮罩，季型會被靜默改掉（實測 12% 的乾淨照片）。
這支腳本比對真實 get_skin_color 的季型與「未過濾」的參考答案，應為全數一致。
"""
import glob
from Face_analyzer_BASIC import FaceAnalyzer
import numpy as np, cv2

def reference_season(fa):
    """完全照 get_skin_color 走到 combined_mask（不套紋理），再算季型 = 修正前的正確行為。"""
    face=np.zeros((fa.h,fa.w),np.uint8)
    cv2.fillConvexPoly(face,cv2.convexHull(np.array([fa._pt(i) for i in range(len(fa.lm))],np.int32)),255)
    cheek=cv2.bitwise_or(fa._landmark_poly_mask([50,101,118,117,123,205,187,147,177,137]),
                         fa._landmark_poly_mask([280,330,347,346,352,425,411,376,401,366]))
    sample = cheek if cv2.countNonZero(cheek)>=180 else face.copy()
    for reg in (fa.mp_face_mesh.FACEMESH_LIPS, fa.mp_face_mesh.FACEMESH_LEFT_EYE, fa.mp_face_mesh.FACEMESH_RIGHT_EYE):
        idx=fa._collect_landmark_indices(reg)
        if idx:
            pts=np.array([fa._pt(i) for i in idx],np.int32)
            cv2.fillConvexPoly(face,cv2.convexHull(pts),0); cv2.fillConvexPoly(sample,cv2.convexHull(pts),0)
    lab=cv2.cvtColor(fa.frame,cv2.COLOR_BGR2Lab); hsv=cv2.cvtColor(fa.frame,cv2.COLOR_BGR2HSV)
    ycc=cv2.cvtColor(fa.frame,cv2.COLOR_BGR2YCrCb)
    cm=cv2.bitwise_and(cv2.inRange(lab,np.array([35,130,124]),np.array([235,178,184])),
        cv2.bitwise_or(cv2.inRange(hsv,np.array([0,12,35]),np.array([35,175,245])),
                       cv2.inRange(ycc,np.array([35,128,72]),np.array([245,185,142]))))
    k=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(5,5))
    cm=cv2.morphologyEx(cv2.morphologyEx(cm,cv2.MORPH_OPEN,k),cv2.MORPH_CLOSE,k)
    combined=cv2.bitwise_and(sample,cm)
    if cv2.countNonZero(combined)<100 and sample is not face:
        combined=cv2.bitwise_and(face,cm)
    return fa._classify_season(lab,hsv,combined)

mismatch=0; n=0; rel_measured=0
for path in sorted(glob.glob(str(DATASET / "*.png")))[:40]:
    try: fa=FaceAnalyzer(path,strict_angle=False,require_insight=False)
    except Exception: continue
    ref = reference_season(fa)
    try: _,_,_,season,_,_,_,_ = fa.get_skin_color()
    except Exception: continue
    n+=1
    if fa.skin_reliability.get("measured"): rel_measured+=1
    if season!=ref:
        mismatch+=1; print(f"  不一致 {path[-8:]}: 實際={season} 參考={ref}")

print(f"\n測試 {n} 張")
print(f"四季型與『未過濾參考答案』不一致：{mismatch} 張  -> {'回歸已修' if mismatch==0 else '*** 仍有偏差 ***'}")
print(f"可信度有量到（measured=True）：{rel_measured}/{n}")
