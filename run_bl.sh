set -x
echo "########## 眉型 · 輪廓遮罩 ##########"
./.venv/Scripts/python.exe -X utf8 train_basic_cnn_roi.py --cv 5 --identity-mode cluster --epochs 40 \
    --parts brow_shape --contour-parts brow_shape
echo "########## 唇型 · 三通道遮罩 ##########"
./.venv/Scripts/python.exe -X utf8 train_basic_cnn_roi.py --cv 5 --identity-mode cluster --epochs 40 \
    --parts lip_shape --contour-parts lip_shape
