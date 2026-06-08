import json

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from Face_analyzer_BASIC import FaceAnalyzer


app = FastAPI(title="Face Analyzer PRO")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _read_image(file: UploadFile, label: str) -> bytes:
    contents = await file.read()
    if not contents:
        raise ValueError(f"{label}照片是空的")
    return contents


def _merge_basic_and_pro(front_result, side_available=False):
    result = dict(front_result)
    result["分析版本"] = "PRO"
    result["精細分析狀態"] = {
        "多角度照片": "已接收" if side_available else "未提供完整側面角度",
        "鼻型精細分類": "待實作",
        "臉型精細分類": "待實作",
    }
    result["精細分析備註"] = (
        "PRO 目前先保留多角度檔案上傳入口；"
        "鷹勾鼻、塌鼻、朝天鼻、翹鼻等側面特徵需等側面/45度特徵演算法完成後再啟用。"
    )
    return result


@app.post("/analyze-pro")
async def analyze_pro(
    front: UploadFile = File(...),
    left45: UploadFile | None = File(default=None),
    right45: UploadFile | None = File(default=None),
    side: UploadFile | None = File(default=None),
):
    """
    PRO 檔案上傳版。

    目前可用流程：
    - front：必填正面照，先沿用 BASIC 的穩定分析。
    - left45/right45/side：先預留欄位，讓前端可以上傳多角度照片。

    掃描版預留：
    - 未來前端使用 getUserMedia 開鏡頭。
    - 依 yaw 自動擷取 front / left45 / right45 / side。
    - 擷取完成後仍送到這個 API，避免掃描版和檔案上傳版後端邏輯分裂。
    """
    try:
        front_bytes = await _read_image(front, "正面")
        front_result = FaceAnalyzer(front_bytes).export_json()

        side_available = False
        for label, upload in (("左45度", left45), ("右45度", right45), ("側面", side)):
            if upload is None:
                continue
            await _read_image(upload, label)
            side_available = True

        return _merge_basic_and_pro(front_result, side_available=side_available)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8002)
