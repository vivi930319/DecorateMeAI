# Decorate Me 服務暖機腳本
# 用途：Demo / 口試前執行，喚醒 Cloud Run 上的臉部分析服務，
#       避免第一位使用者按分析時遇到冷啟動（載入 InsightFace 與 ONNX 模型）。
#       實測冷啟動：face-basic 平均 15 秒（最慢約 27 秒）、face-pro 平均 8 秒。
# 用法：demo 前 2-3 分鐘執行  ->  .\warmup.ps1
#
# 這支腳本**必須帶 ID token**。這幾支服務都是 --no-allow-unauthenticated，沒帶 token 時
# Cloud Run 會在 Google 前端就回 403，請求**根本到不了容器**——沒帶 token 的暖機腳本
# 一台 instance 都叫不醒，只是印一排紅字而已。
# 2026-08-17 之前這支腳本正是如此（三個網址實測全部 403）。當時 min-instances=1 讓服務
# 24/7 熱著，暖不暖機結果都一樣，所以沒有人發現它是空轉的——設定把 bug 蓋住了。

$urls = @(
    "https://face-basic-258021445391.asia-east1.run.app/health",
    "https://face-pro-258021445391.asia-east1.run.app/health",
    # replicate-render 從 2026-09-09 起也是 min-instances=0（常駐一台每月約 NT$1,700，
    # 而它一週只收 9,131 次請求，錢多數花在沒人用的時候）。所以它現在**也會冷啟動**，
    # 這一行不再只是探活，是真的要暖它。
    "https://replicate-render-258021445391.asia-east1.run.app/health"
)

# 不要加 --audiences：使用者帳號憑證簽不出指定 audience 的 ID token（gcloud 會直接拒絕，
# 回 "Requires valid service account."）。不帶 audiences 的 token 實測可以通過 Cloud Run
# 的 IAM 檢查（2026-08-17 對 face-basic /health 實測回 200）。
$token = (& gcloud.cmd auth print-identity-token).Trim()
if (-not $token) {
    Write-Host "拿不到 ID token，請先執行 gcloud auth login。" -ForegroundColor Red
    Write-Host "沒有 token 的話每個請求都會是 403，容器不會啟動，等於完全沒暖到機。" -ForegroundColor Red
    exit 1
}
$headers = @{ Authorization = "Bearer $token" }

Write-Host "開始暖機（第一次可能較久，因為要載入模型）..." -ForegroundColor Cyan
foreach ($u in $urls) {
    try {
        $t = Measure-Command { $r = Invoke-WebRequest -Uri $u -Headers $headers -TimeoutSec 90 -UseBasicParsing }
        Write-Host ("  OK   {0,-6} {1,6:N1}s  {2}" -f $r.StatusCode, $t.TotalSeconds, $u) -ForegroundColor Green
    } catch {
        # 403 在這裡幾乎都代表 token 有問題，而不是服務有問題——服務壞掉會是 5xx。
        Write-Host ("  FAIL        {0}  ->  {1}" -f $u, $_.Exception.Message) -ForegroundColor Red
    }
}
Write-Host "暖機完成。face 服務閒置一段時間後會再縮回 0，接近 demo 時再跑一次最保險。" -ForegroundColor Cyan

# 想要「demo 全程完全不冷啟動」的話，改用常駐部署（會產生費用，每支每天約 NT$246）：
#   .\deploy_face_cloudrun.ps1 -MinInstances 1
# 結束後用預設值重新部署就會回到 0：
#   .\deploy_face_cloudrun.ps1
#
# 不想重建映像、只要臨時切換的話（30 秒，沿用現有映像）：
#   gcloud run services update face-basic --region=asia-east1 --min-instances=1
#   gcloud run services update face-pro   --region=asia-east1 --min-instances=1
# 但下次有人跑 deploy_face_cloudrun.ps1 會用參數預設值把它蓋回 0——那是刻意的，
# 免得 demo 完沒有人記得關。忘記關的代價是每天 NT$492。
