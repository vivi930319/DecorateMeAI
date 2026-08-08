set -x
echo "########## 1) 高解析度輪廓遮罩 224 ##########"
./.venv/Scripts/python.exe -X utf8 tools/prepare_face_contour_cache.py --size 224
./.venv/Scripts/python.exe -X utf8 train_basic_cnn_roi.py --cv 5 --identity-mode cluster --epochs 40 \
    --parts face_shape --face-input contour --contour-file face_contour_224.npy
cp models/basic_features_roi/cv_summary_contour.json models/basic_features_roi/cv_summary_face_contour224.json
echo "########## 2) 幾何特徵（含新的下顎曲率）決策樹 ##########"
./.venv/Scripts/python.exe -X utf8 tools/cv_rule_baseline.py --refresh --parts face_shape
