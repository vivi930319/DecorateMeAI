import os
import json
import math  # 用於圓形的計算
from PIL import Image


YOLO_CLASSES = [
    "dark_circle_L",
    "dark_circle_R",
    "mouth",
    "eyebrow_L",
    "eyebrow_R",
    "nose_hightlight_up",
    "nose_hightlight_down",
    "eye_left",
    "eye_right",
    "acne",
]

JSON_DIR = r"C:\組員的資料庫-20251121T022433Z-1-001\組員的資料庫\facedata"  # 存放所有 .json 文件的資料夾
IMAGE_DIR = r"C:\組員的資料庫-20251121T022433Z-1-001\組員的資料庫"  # 存放所有圖片的資料夾
OUTPUT_DIR = './yolov8_labels/'  # 輸出 .txt 文件的目標資料夾



def convert_labelme_to_yolo(json_file_path):
    """
    將單個 LabelMe JSON 文件轉換為 YOLO Bounding Box (Detection) TXT 格式。
    格式: [Class_ID] [center_x_norm] [center_y_norm] [width_norm] [height_norm]
    """

    # 讀取 JSON 文件
    try:
        with open(json_file_path, 'r', encoding='utf8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"錯誤：無法讀取 JSON 文件 {json_file_path}. 錯誤: {e}")
        return

    # --- 修正 1: 準確解析相對圖片路徑 (解決找不到圖片的問題) ---
    json_base_dir = os.path.dirname(json_file_path)
    relative_image_path = data.get('imagePath', '')
    image_path = os.path.normpath(os.path.join(json_base_dir, relative_image_path))

    # 檢查圖片是否存在
    if not os.path.exists(image_path):
        print("-" * 60)
        print(f"錯誤：找不到圖片，轉換跳過。")
        print(f"   - 嘗試尋找路徑：{image_path}")
        print(f"   - 請確認圖片是否確實位於該絕對路徑下。")
        print("-" * 60)
        return

    # 獲取圖片寬高
    try:
        img = Image.open(image_path)
        img_w, img_h = img.size
    except Exception as e:
        print(f"錯誤：無法打開或讀取圖片尺寸 {image_path}. 錯誤: {e}")
        return

    yolo_content = []

    for shape in data['shapes']:
        label = shape['label']
        points = shape['points']
        shape_type = shape['shape_type']

        if label not in YOLO_CLASSES:
            print(f"警告：跳過未知標籤 '{label}'，請檢查拼寫。")
            continue

        class_id = YOLO_CLASSES.index(label)

        # --- 修正 2: 處理所有形狀類型 ---

        x_min, y_min, x_max, y_max = 0, 0, 0, 0

        if shape_type == 'polygon' or shape_type == 'rectangle':
            # 對於多邊形和矩形，找出所有點的最小/最大座標作為邊界框
            x_coords = [p[0] for p in points]
            y_coords = [p[1] for p in points]
            x_min, y_min = min(x_coords), min(y_coords)
            x_max, y_max = max(x_coords), max(y_coords)

        elif shape_type == 'circle':
            # 圓形有兩個點：圓心 (center) 和半徑上的點 (radius_point)
            center_x, center_y = points[0]
            radius_x, radius_y = points[1]

            # 計算半徑 (兩點間距離)
            radius = math.sqrt((center_x - radius_x) ** 2 + (center_y - radius_y) ** 2)

            # 圓形的外接矩形
            x_min = center_x - radius
            y_min = center_y - radius
            x_max = center_x + radius
            y_max = center_y + radius

        else:
            print(f"警告：跳過不支援的形狀類型 '{shape_type}' 標記 '{label}'")
            continue

        # 轉換為 YOLO Bounding Box 格式 (x_center, y_center, width, height)

        # 邊界框寬高
        bbox_w = x_max - x_min
        bbox_h = y_max - y_min
        # 中心點
        center_x = x_min + bbox_w / 2
        center_y = y_min + bbox_h / 2

        # 歸一化
        x_norm = center_x / img_w
        y_norm = center_y / img_h
        w_norm = bbox_w / img_w
        h_norm = bbox_h / img_h

        # 組合 YOLO 格式字串
        line = f"{class_id} {x_norm:.6f} {y_norm:.6f} {w_norm:.6f} {h_norm:.6f}"
        yolo_content.append(line)

    # 寫入 YOLO TXT 文件
    base_name = os.path.splitext(os.path.basename(json_file_path))[0]
    output_txt_path = os.path.join(OUTPUT_DIR, base_name + '.txt')

    if yolo_content:
        with open(output_txt_path, 'w', encoding='utf8') as f:
            f.write("\n".join(yolo_content))
        print(f"成功轉換: {base_name}.txt (包含 {len(yolo_content)} 個標記)")
    else:
        print(f"警告: {base_name}.json 沒有有效標記或標記被跳過，跳過創建 .txt 文件。")



if __name__ == '__main__':
    # 檢查並創建輸出資料夾
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    print(f"總共 {len(YOLO_CLASSES)} 個類別將被轉換為 YOLO Detection Bounding Box 格式。")

    # 遍歷 JSON 資料夾中的所有文件
    for filename in os.listdir(JSON_DIR):
        if filename.endswith('.json'):
            json_path = os.path.join(JSON_DIR, filename)
            convert_labelme_to_yolo(json_path)

    print("\n所有文件轉換完成。請檢查 output 資料夾。")