$ErrorActionPreference = 'Stop'

# 與 Cloud Run Gateway 使用相同的固定 Secret Manager 版本。金鑰只存在於
# 這個 PowerShell 行程與 Docker 容器環境，不寫入專案 .env 或日誌。
$memberKey = gcloud secrets versions access 2 `
    --secret=decorate-me-member-upstream-key `
    --project=decorate-me

if ([string]::IsNullOrWhiteSpace($memberKey)) {
    throw '無法取得 decorate-me-member-upstream-key，會員服務未啟動。'
}

$env:UPSTREAM_MEMBER_API_KEY = $memberKey.Trim()
try {
    docker compose up -d --build app
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose 啟動失敗，exit code: $LASTEXITCODE"
    }
}
finally {
    Remove-Item Env:UPSTREAM_MEMBER_API_KEY -ErrorAction SilentlyContinue
}
