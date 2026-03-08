#這裡最後去裉預測圖片有無預測正確(有沒有描繪到該五官的依據)
#要看結果記得要跑這個
from ultralytics import YOLO
import os

model_path = r'C:\Users\isach\PycharmProjects\makeup_facing\facing_ba\runs\detect\makeup_facing_v15\weights\best.pt'
model = YOLO(model_path)


source_path = r'C:\Users\isach\PycharmProjects\makeup_facing\My_Project_Data\images\val'

print(f"開始使用模型{os.path.basename(model_path)} 進行預測...")


results = model.predict(
    source=source_path,
    conf=0.005,#信任參數
    save=True,        # 自動保存結果
    name='test_results'
)

print("\n 結果完成。")