# Decorate Me GitHub 工程化規劃（9/19 發表版）

> 適用專案：Decorate Me（AI 美妝推薦系統） 目標：在不重建
> Repository、不修改 Git 歷史的前提下，將 GitHub
> 專案提升到接近業界團隊開發水準。

------------------------------------------------------------------------

# 一、目前專案現況

目前 Repository 已具備：

-   GitHub Repository
-   多個 Branch
-   Commit 紀錄
-   Docker
-   Cloud Run
-   Firebase Hosting
-   FastAPI
-   微服務架構

目前缺少：

-   Pull Request 流程
-   GitHub Issues
-   GitHub Projects
-   Release 管理
-   完整 README
-   CHANGELOG
-   GitHub Actions
-   PR Template
-   Issue Template

------------------------------------------------------------------------

# 二、舊 Branch 要不要刪？

## 結論：不用。

保留目前所有 Branch：

``` text
main
dev
dev_makeup
Amy
Isa
lavien
```

原因：

1.  保留完整開發歷史。
2.  不需要重寫 Git Commit。
3.  工程師通常不會為了整理 GitHub 而刪除歷史。

如果 Branch 已完成：

-   Merge 到 develop（若仍有內容）
-   或直接保留
-   或確認沒用後刪除 Remote Branch

------------------------------------------------------------------------

# 三、建立新的 Git Flow

新增：

``` text
main
│
develop
│
├── feature/frontend
├── feature/member
├── feature/face-analysis
├── feature/render
├── feature/recommend
├── feature/history
├── feature/admin
│
├── hotfix/login
│
└── release/v1.0
```

之後所有新功能都從 `develop` 開出 `feature/*`。

------------------------------------------------------------------------

# 四、Git 工作流程

``` text
Issue
 ↓
feature Branch
 ↓
開發
 ↓
Commit
 ↓
Push
 ↓
Pull Request
 ↓
Code Review
 ↓
Merge 到 develop
 ↓
Release
 ↓
Merge 到 main
```

------------------------------------------------------------------------

# 五、Commit Message 規範

``` text
feat(frontend): add login page

feat(face): add skin tone analysis

feat(render): integrate Replicate API

feat(member): add favorite looks

fix(api): resolve CORS issue

fix(render): fix timeout

docs: update README

refactor(face): optimize landmark calculation

style(ui): improve dashboard layout
```

避免：

``` text
update
修改
aaa
123
test
```

------------------------------------------------------------------------

# 六、GitHub Issues

建議建立：

-   Login
-   Member Center
-   Face Analysis
-   AI Render
-   Product Recommendation
-   History
-   Admin Dashboard

Bug：

-   Upload Failed
-   Render Timeout
-   Face Detection Failed

------------------------------------------------------------------------

# 七、Pull Request

流程：

``` text
feature/history
        │
        ▼
Open Pull Request
        │
        ▼
Code Review
        │
        ▼
Merge 到 develop
```

PR 標題：

``` text
feat(history): complete history page

fix(render): resolve timeout issue
```

------------------------------------------------------------------------

# 八、GitHub Projects

建立 Kanban：

``` text
Backlog

↓

Todo

↓

In Progress

↓

Testing

↓

Done
```

------------------------------------------------------------------------

# 九、Milestones

``` text
v0.5 Face Analysis

v0.7 Render

v0.9 Beta

v1.0 Graduation Demo

v1.1 Bug Fix

v2.0 Official
```

------------------------------------------------------------------------

# 十、Releases

``` text
v0.9 Beta

v1.0 Graduation Demo

v1.1 Bug Fix

v2.0 Official
```

------------------------------------------------------------------------

# 十一、README

建議包含：

-   專案介紹
-   系統架構圖
-   技術架構
-   API
-   Docker
-   Cloud Run
-   Firebase
-   安裝方式
-   團隊介紹

------------------------------------------------------------------------

# 十二、GitHub Actions（加分）

``` text
Push
 ↓
Build
 ↓
Test
 ↓
Docker Build
 ↓
Deploy Cloud Run
```

------------------------------------------------------------------------

# 十三、9/19 前建議時程

## 第1週

-   建立 develop
-   建立 feature/\*
-   更新 README

## 第2週

-   開始使用 GitHub Issues

## 第3週

-   所有功能改走 Pull Request

## 第4週

-   建立 GitHub Projects

## 第5週

-   建立 Beta Release

## 第6週

-   補齊 README 與 docs

## 第7週

-   建立 CHANGELOG

## 第8週

-   Bug 修正

## 第9週

-   發布 v1.0

------------------------------------------------------------------------

# 十四、建議新增文件

``` text
docs/
├── System_Architecture.md
├── API_Spec.md
├── Deployment.md
├── Docker_Architecture.md
├── Security.md
├── Branch_Strategy.md
├── Git_Workflow.md
├── CHANGELOG.md
├── CONTRIBUTING.md
└── CODEOWNERS
```

------------------------------------------------------------------------

# 最終目標

保留目前所有開發成果，不修改歷史紀錄。

從現在開始導入：

-   Git Flow
-   Pull Request
-   Code Review
-   GitHub Issues
-   GitHub Projects
-   Release
-   CHANGELOG
-   README
-   GitHub Actions（可選）

完成後，GitHub
將更符合業界團隊開發流程，也能作為畢業專題展示與履歷作品集。
