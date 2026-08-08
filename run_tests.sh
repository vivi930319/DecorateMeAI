set -x
echo "########## A：眼型合併實驗（6類 -> 4類）##########"
./.venv/Scripts/python.exe -X utf8 train_basic_cnn_roi.py --cv 5 --identity-mode cluster --merge-eye --parts eye_shape
echo "########## B：重訓最終模型（含 DINOv2 head，修正 8 類殘留）##########"
./.venv/Scripts/python.exe -X utf8 tools/train_final_selected_models.py
