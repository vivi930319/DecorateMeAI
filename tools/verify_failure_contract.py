"""正反項測試：分析成功要成功，該失敗的要用正確的碼失敗。

這輪動到了 job 的失敗出口（fail_job）、失敗的判定方式（UnusableImageError 取代
「訊息裡有沒有中文」）、以及 PRO 的膚色來源（側面照退出）。這三件事都沒有既有測試
守著，所以在這裡一次蓋住。

跑法：
    .venv/Scripts/python.exe tools/verify_failure_contract.py

需要測試照片資料集；路徑見下方 FRONT_DIR / SIDE_DIR。
"""
import glob
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
import numpy as np
import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 專案模組要等 ROOT 進 sys.path 之後才 import 得到，所以這幾行不能往上搬。
import Face_analyzer_BASIC as B  # noqa: E402
import Face_analyzer_PRO as PRO  # noqa: E402
from Face_analyzer_BASIC import FaceAnalyzer, UnusableImageError  # noqa: E402
from analysis_package import normalize_face_analysis  # noqa: E402

FRONT_DIR = ROOT / "data" / "kaggle_asian_faces" / "generated_yellow-stylegan2"
SIDE_DIR = ROOT / "data" / "pro_full" / "grouped" / "nose_shape_side"

failures = []


def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        print(f"        得到 {got!r}\n        預期 {want!r}")
        failures.append(name)


def capture_fail_job(exc):
    """把例外送進真正的 fail_job，回傳它寫出去的 patch。"""
    captured = []

    class FakeStore:
        def patch_if_status(self, col, job_id, statuses, patch):
            captured.append(patch)

    real, B.job_store = B.job_store, FakeStore()
    try:
        try:
            raise exc
        except Exception as e:
            B.fail_job("col", "job", e, log_label="測試")
    finally:
        B.job_store = real
    return captured[0]


print("=" * 62)
print("正項：正常照片要分析成功")
print("=" * 62)

front_paths = sorted(glob.glob(str(FRONT_DIR / "*.png")))
side_paths = sorted(glob.glob(str(SIDE_DIR / "*" / "*")))
if not front_paths or not side_paths:
    print("找不到測試照片，無法執行。請確認 FRONT_DIR / SIDE_DIR。")
    sys.exit(2)

front_raw = FaceAnalyzer(front_paths[0]).export_json()
check("BASIC 分析出臉型", bool(front_raw.get("臉型")), True)
check("BASIC 分析出膚色 LAB", bool(front_raw.get("膚色", {}).get("LAB")), True)

basic_pkg = normalize_face_analysis(front_raw)
check("BASIC schemaVersion", basic_pkg["version"], basic_pkg["version"])
check("BASIC labReliable 是布林", isinstance(basic_pkg["skinTone"]["labReliable"], bool), True)
check("BASIC sidePhotoUsed", basic_pkg["sidePhotoUsed"], False)

side_result = PRO._analyze_side_supplementary(open(side_paths[0], "rb").read())
merged = PRO._merge_basic_and_pro(front_raw, side_result=side_result)
pro_pkg = normalize_face_analysis(merged)

check("PRO 膚色 LAB 等於正面照", merged["膚色"]["LAB"], front_raw["膚色"]["LAB"])
check("PRO 可信度沿用正面照", merged["膚色"]["可信度"], front_raw["膚色"]["可信度"])
check("PRO 側面結果不含膚色", "膚色" in (side_result or {}), False)
check("PRO labSource", pro_pkg["skinTone"]["labSource"], "正面照")
check("PRO sidePhotoUsed", pro_pkg["sidePhotoUsed"], True)

print()
print("=" * 62)
print("反項：每一種失敗都要用正確的碼與訊息")
print("=" * 62)

print("\n-- 照片問題 -> FACE_IMAGE_UNUSABLE，訊息原樣傳出去 --")
blank = cv2.imencode(".png", np.full((400, 400, 3), 200, np.uint8))[1].tobytes()
try:
    FaceAnalyzer(blank)
    check("無人臉照片要丟例外", "沒有丟", "UnusableImageError")
except UnusableImageError as e:
    check("無人臉照片的例外型別", type(e).__name__, "UnusableImageError")
    p = capture_fail_job(e)
    check("  stage", p["stage"], "unusable_image")
    check("  code", p["error"]["code"], "FACE_IMAGE_UNUSABLE")
    check("  message 原樣", p["error"]["message"], "沒偵測到人臉")
    check("  retryable", p["error"]["retryable"], True)

try:
    FaceAnalyzer(b"this is not an image")
    check("壞掉的檔案要丟例外", "沒有丟", "UnusableImageError")
except UnusableImageError as e:
    p = capture_fail_job(e)
    check("壞檔 code", p["error"]["code"], "FACE_IMAGE_UNUSABLE")
    check("壞檔 message 可行動", "JPG" in p["error"]["message"], True)

print("\n-- 內部錯誤 -> FACE_ANALYSIS_ERROR，訊息不外流 --")
GENERIC = "臉部分析失敗，請稍後再試"
for label, exc in [
    ("型別傳錯（訊息含中文，先前會被誤判）", ValueError("image_input 只接受 str 或 bytes")),
    ("cv2 英文錯誤", ValueError("!_src.empty() in function cvtColor")),
    ("非 ValueError", RuntimeError("boom")),
    ("KeyError", KeyError("膚色")),
]:
    p = capture_fail_job(exc)
    check(f"{label} -> code", p["error"]["code"], "FACE_ANALYSIS_ERROR")
    check(f"{label} -> 用固定訊息", p["error"]["message"], GENERIC)

print("\n-- 型別關係：舊呼叫端不能被改壞 --")
check("UnusableImageError 是 ValueError", issubclass(UnusableImageError, ValueError), True)
try:
    FaceAnalyzer(blank)
except ValueError as e:
    check("except ValueError 仍抓得到", isinstance(e, UnusableImageError), True)

try:
    FaceAnalyzer(12345)
    check("型別傳錯要丟例外", "沒有丟", "ValueError")
except UnusableImageError:
    check("型別傳錯不可以是 UnusableImageError", "是", "不是")
except ValueError:
    check("型別傳錯是一般 ValueError", True, True)

print()
print("=" * 62)
if failures:
    print(f"失敗 {len(failures)} 項：")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("全部通過")
sys.exit(0)
