set -x
# 等前一條鏈結束（它會寫出 cv_summary_best_hp.json），避免兩邊搶同一批檔案
for i in $(seq 1 360); do
  [ -f models/basic_features_roi/cv_summary_best_hp.json ] && break
  sleep 15
done
for LR in 3e-4 6e-4; do
  echo "########## 匯出 40 epochs / lr=$LR 的模型 ##########"
  ./.venv/Scripts/python.exe -X utf8 train_basic_cnn_roi.py --skip-random --epochs 40 --learning-rate $LR
  echo "########## Hybrid 門檻（CNN = 40ep/$LR）##########"
  ./.venv/Scripts/python.exe -X utf8 tools/tune_hybrid.py
  cp models/basic_features_roi/hybrid_config.json "models/basic_features_roi/hybrid_config_ep40_lr${LR}.json"
done
# 還原成備份的 onnx —— 這一輪只是實驗，不動部署候選
cp models/_onnx_backup_20260729/*.onnx models/basic_features_roi/
echo "已還原 onnx 備份"
