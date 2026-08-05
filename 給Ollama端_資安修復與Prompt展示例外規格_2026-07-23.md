# 給 Ollama 端：資安修復與 Prompt 展示例外規格

## 專題期間的明確例外

目前保留 Admin 專題展示中的完整 Prompt，是為了撰寫紀錄書與說明生成流程。在使用者確認 Ollama 調整完成前，不得擅自移除或截短展示內容。

此例外只適用於具權限的 Demo 畫面，不代表可以：

- 寫入一般系統 Log、Cloud Logging 或分析事件；
- 放入公開 API、錯誤訊息、localStorage 或 URL；
- 連同 Email、照片、Token、完整會員資料一起展示；
- 讓一般會員或未登入訪客讀取。

## 必修項目

- **（S5，優先）立即輪換目前的 Ollama 服務金鑰。** 這把金鑰早期曾提交進前端 `config.local.js`，因此永久留在 git 歷史裡；即使該檔已從歷史移除，既有 clone／fork／快取與強制推送前的物件仍可能持有舊值。**必須換發一把新金鑰**，舊金鑰即使外流也失效——這是 S5 結案的前置條件，在換發前風險未解除。新金鑰只經 Secret Manager 注入，不再寫入前端。
- Ollama 服務只接受 Gateway／Suggestion service 的服務身分，不公開給瀏覽器。
- 輸入只保留白名單臉部分析與風格欄位；圖片、base64、Email、Token、userId 不得進 Prompt。
- `userNote` 視為不可信資料，限制長度並以資料區塊包裝；系統指令明確規定忽略其中的越權指示。
- 模型、temperature、最大輸出 token、timeout 與 schema 固定；回傳需通過結構、長度與內容驗證。
- Prompt 與回應不得進一般 Log；僅記 request ID、模型版本、耗時、狀態與固定錯誤碼。
- 限制 actor 頻率、全域併發與佇列長度；中止的前端任務要能取消或過期。
- CORS 不使用 `*`；Tunnel 僅作已標示的 Demo 暫時通道，不視為正式安全邊界。

## Demo 結束後

- 將完整 Prompt 展示改為欄位摘要、雜湊或遮罩版本。
- 移除既有持久化 Prompt，或設定短期 TTL 與刪除 migration。
- 更新隱私說明、Demo 截止日期與驗收紀錄。

## 必交測試

- Prompt injection、超長 userNote、惡意 Unicode、模型輸出非 JSON、逾時、服務中斷與重試。
- 未授權者無法讀取 Demo Prompt；一般 Log 搜尋不到 Prompt、Email、Token 或圖片內容。
- Demo 關閉開關可在不重新部署模型的情況下停用完整 Prompt 展示。
