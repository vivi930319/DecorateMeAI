from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from makeup_ai9 import get_makeup_suggestion
import os

app = FastAPI()


class FaceData(BaseModel):
    style: str = "韓系亞裔妝"
    skin_tone: str = "春季型"
    face_shape: str = "鵝蛋臉"
    eye_features: str = "雙眼皮"
    nose_type: str = "直鼻"
    lip_type: str = "微笑唇"
    eyebrow_type: str = "標準眉"

@app.get("/")
async def root():
    """
    測試用路徑，確認 API 是否在 Docker 內正常啟動
    """
    return {
        "status": "online", 
        "message": "AI 化妝建議 API 已啟動 (Docker 模式)",
        "student_id": "412630591",
        "name": "黃姵錚"
    }

@app.post("/analyze-makeup")
async def analyze_makeup(data: FaceData):
    """
    接收 MediaPipe 的 JSON 特徵，並呼叫妳的專業資料庫生成建議
    """
    try:
  
        advice = get_makeup_suggestion(
            skin=data.skin_tone,
            face=data.face_shape,
            eye=data.eye_features,
            nose=data.nose_type,
            lip=data.lip_type,
            eyebrow=data.eyebrow_type,
            style_name=data.style
        )
        
        return {
            "status": "success",
            "style_requested": data.style,
            "ai_advice": advice
        }
        
    except Exception as e:
       
        raise HTTPException(status_code=500, detail=f"發生錯誤：{str(e)}")

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(app, host="0.0.0.0", port=8000)