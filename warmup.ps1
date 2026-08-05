# Decorate Me 服務暖機腳本
# 用途：Demo / 口試前執行，喚醒 Cloud Run 上的臉部分析與渲染服務，
#       避免第一位使用者按分析/渲染時遇到冷啟動（載模型）卡 10-30 秒。
# 用法：demo 前 2-3 分鐘執行  ->  .\warmup.ps1
# 注意：Cloud Run 閒置約 15 分鐘會再縮回 0，需要時重跑即可。

$urls = @(
    "https://face-basic-258021445391.asia-east1.run.app/health",
    "https://face-pro-258021445391.asia-east1.run.app/health",
    "https://replicate-render-258021445391.asia-east1.run.app/health"
)

Write-Host "開始暖機（第一次可能較久，因為要載入模型）..." -ForegroundColor Cyan
foreach ($u in $urls) {
    try {
        $t = Measure-Command { $r = Invoke-WebRequest -Uri $u -TimeoutSec 90 -UseBasicParsing }
        Write-Host ("  OK   {0,-6} {1,6:N1}s  {2}" -f $r.StatusCode, $t.TotalSeconds, $u) -ForegroundColor Green
    } catch {
        Write-Host ("  FAIL        {0}  ->  {1}" -f $u, $_.Exception.Message) -ForegroundColor Red
    }
}
Write-Host "暖機完成。若距離 demo 超過 ~15 分鐘，開始前再跑一次。" -ForegroundColor Cyan

# 想要「demo 期間完全不冷啟動」的話（會有常駐費用，demo 完記得改回 0）：
#   gcloud run services update face-basic       --region=asia-east1 --min-instances=1
#   gcloud run services update face-pro          --region=asia-east1 --min-instances=1
#   gcloud run services update replicate-render  --region=asia-east1 --min-instances=1
# 改回：把 --min-instances=1 換成 --min-instances=0
