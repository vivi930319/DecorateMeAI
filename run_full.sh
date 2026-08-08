set -x
./.venv/Scripts/python.exe -X utf8 tools/build_identity_map.py
./.venv/Scripts/python.exe -X utf8 prepare_roi_cache.py
echo "########## 模型一：CNN 5-fold ##########"
./.venv/Scripts/python.exe -X utf8 train_basic_cnn_roi.py --cv 5 --identity-mode cluster
echo "########## 模型二：幾何決策樹 5-fold ##########"
./.venv/Scripts/python.exe -X utf8 tools/calibrate_rule_thresholds.py
./.venv/Scripts/python.exe -X utf8 tools/cv_rule_baseline.py --refresh
echo "########## 模型三：DINOv2 5-fold ##########"
./.venv/Scripts/python.exe -X utf8 tools/dinov2_cv_experiment.py
echo "########## 匯出部署模型 ##########"
./.venv/Scripts/python.exe -X utf8 train_basic_cnn_roi.py --skip-random
