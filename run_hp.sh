set -x
run () {   # $1=標籤  其餘=參數
  tag=$1; shift
  echo "########## $tag ##########"
  ./.venv/Scripts/python.exe -X utf8 train_basic_cnn_roi.py --cv 5 --identity-mode cluster "$@"
  cp models/basic_features_roi/cv_summary.json "models/basic_features_roi/cv_summary_hp_${tag}.json"
}
run ep40_lr3e4  --epochs 40
run ep20_lr1e4  --epochs 20 --learning-rate 1e-4
run ep40_lr1e4  --epochs 40 --learning-rate 1e-4
run ep40_lr6e4  --epochs 40 --learning-rate 6e-4
