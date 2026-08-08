set -x
./.venv/Scripts/python.exe -X utf8 tools/prepare_face_contour_cache.py
echo "########## 臉型 · RGB（對照組，identity 切分 40 epochs）##########"
./.venv/Scripts/python.exe -X utf8 train_basic_cnn_roi.py --cv 5 --identity-mode cluster --epochs 40 --parts face_shape
cp models/basic_features_roi/cv_summary.json models/basic_features_roi/cv_summary_face_rgb.json
echo "########## 臉型 · 輪廓遮罩 ##########"
./.venv/Scripts/python.exe -X utf8 train_basic_cnn_roi.py --cv 5 --identity-mode cluster --epochs 40 --parts face_shape --face-input contour
cp models/basic_features_roi/cv_summary.json models/basic_features_roi/cv_summary_face_contour.json
