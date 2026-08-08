set -x
./.venv/Scripts/python.exe -X utf8 prepare_roi_cache.py
echo "########## 桃杏眼 5 類 · CNN 40 epochs 5-fold ##########"
./.venv/Scripts/python.exe -X utf8 train_basic_cnn_roi.py --cv 5 --identity-mode cluster --epochs 40 --parts eye_shape
cp models/basic_features_roi/cv_summary.json models/basic_features_roi/cv_summary_taoxing.json
echo "########## 桃杏眼 5 類 · DINOv2 ##########"
./.venv/Scripts/python.exe -X utf8 tools/dinov2_cv_experiment.py --parts eye_shape
