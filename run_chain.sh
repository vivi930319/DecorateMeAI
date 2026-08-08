set -x
# 等第四組超參數跑完（它會寫出這個檔）
for i in $(seq 1 240); do
  [ -f models/basic_features_roi/cv_summary_hp_ep40_lr6e4.json ] && break
  sleep 15
done
echo "########## 用最佳設定重訓 CNN（40 epochs / 3e-4）##########"
./.venv/Scripts/python.exe -X utf8 train_basic_cnn_roi.py --cv 5 --identity-mode cluster --epochs 40
cp models/basic_features_roi/cv_summary.json models/basic_features_roi/cv_summary_best_hp.json
echo "########## ① Hybrid 門檻 ##########"
./.venv/Scripts/python.exe -X utf8 tools/tune_hybrid.py
