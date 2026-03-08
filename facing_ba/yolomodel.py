from ultralytics import YOLO

# 1. 載入模型 (使用官方預訓練權重)
model = YOLO('yolo11n.pt')

# 2. 開始訓練 (直接在一個指令內寫完所有參數)
results = model.train(
    data='my_data.yaml',
    epochs=200,  # 訓練週期
    imgsz=640,  # 圖片尺寸
    batch=8,  # 一次看多少圖片，減少消耗cpu內存
    patience=70,  # 如果模型重複七十次沒進步就停止
    optimizer='AdamW',  # 嘗試 AdamW 優化器
    workers=6,  # 載入多少cpu
    name='v16_no_flip_final',  # 儲存資料夾名稱

    #
    fliplr=0.0,  # 徹底禁止左右翻轉 (重要：防止左右辨識錯誤)
    flipud=0.0,  # 徹底禁止上下翻轉

    # 其他建議參數
    augment=True,  # 開啟數據增強，但會排除上面被禁用的翻轉
    mosaic=1.0,  # 拼貼增強 (增加複雜度，但不改變左右邏輯)
    degrees=0.0,  # 如果怕旋轉也會影響左右判定，可以設為 0
)

