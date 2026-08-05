# Git 管控與版本控制改善建議（AI 美妝專題）

## 目前專案狀況

目前專案已經具備 Git 基本版本控制能力：

-   ✅ 使用 GitHub Repository 管理程式碼
-   ✅ 有 Commit 紀錄
-   ✅ 有多個 Branch（main、dev、dev_makeup、Isa、Amy、lavien）

代表已經做到基本版本控制，但距離一般軟體工程團隊的 Git
管控流程仍有提升空間。

------------------------------------------------------------------------

# 建議導入的 Git Flow

    main
    │
    ├── develop
    │    ├── feature/login
    │    ├── feature/makeup-analysis
    │    ├── feature/member
    │    ├── feature/recommend
    │    └── feature/history
    │
    ├── hotfix/api-error
    │
    └── release/v1.0

流程：

    feature/*
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

------------------------------------------------------------------------

# Commit Message 規範

建議使用 Conventional Commits：

  類型       用途       範例
  ---------- ---------- ---------------------------------
  feat       新功能     feat: add login API
  fix        修正 Bug   fix: correct upload bug
  docs       文件       docs: update README
  style      UI、排版   style: adjust navbar layout
  refactor   重構       refactor: optimize FaceAnalyzer
  test       測試       test: add unit tests

避免：

-   update
-   修改
-   test123
-   aaa

------------------------------------------------------------------------

# Branch 命名

    main
    develop
    feature/login
    feature/member
    feature/history
    feature/makeup-analysis
    hotfix/api-error
    release/v1.0

------------------------------------------------------------------------

# Pull Request

每完成一項功能：

    feature/login

    ↓

    Open Pull Request

    ↓

    Code Review

    ↓

    Approve

    ↓

    Merge

PR 標題建議：

    feat: Login Module
    feat: AI Makeup Recommendation
    fix: Upload Image Error

------------------------------------------------------------------------

# GitHub Issues

建立待辦與 Bug：

-   Issue #1 登入功能
-   Issue #2 收藏功能
-   Issue #3 AI 推薦速度過慢
-   Issue #4 API 回傳錯誤

可加上 Label：

-   bug
-   enhancement
-   documentation
-   frontend
-   backend
-   AI

------------------------------------------------------------------------

# GitHub Projects（Kanban）

Todo

-   Login
-   Recommendation
-   History
-   Member

In Progress

-   Face Analysis

Done

-   Database
-   UI
-   API

------------------------------------------------------------------------

# Milestones

建立版本里程碑：

-   v0.1 完成登入
-   v0.5 完成 AI 分析
-   v1.0 畢業專題 Demo
-   v1.1 Bug Fix
-   v2.0 正式版本

------------------------------------------------------------------------

# Releases

發布版本：

-   v1.0 畢業專題展示版
-   v1.1 Bug 修正
-   v1.2 收藏功能
-   v2.0 正式版

------------------------------------------------------------------------

# README 建議

README 至少包含：

-   專案介紹
-   系統架構圖
-   功能介紹
-   技術架構
-   API 文件
-   Docker 部署方式
-   安裝教學
-   作者

------------------------------------------------------------------------

# GitHub Actions（CI/CD）

建議流程：

    Push

    ↓

    自動測試

    ↓

    Docker Build

    ↓

    Railway Deploy

    ↓

    完成部署

可加入：

-   Python 測試
-   Java 測試
-   Docker Build
-   Railway 自動部署

------------------------------------------------------------------------

# Branch Protection

建議設定：

-   禁止直接 Push 到 main
-   必須透過 Pull Request
-   至少一位 Reviewer
-   通過檢查才能 Merge

------------------------------------------------------------------------

# 畢業專題建議完成度

  項目              建議
  ----------------- ----------------------
  Repository        ✅
  Commit Message    ✅ 規範化
  Branch            ✅ develop + feature
  Pull Request      ✅
  Code Review       ✅
  Issues            ✅
  GitHub Projects   ✅
  Milestones        ✅
  Releases          ✅
  README            ✅ 完整
  GitHub Actions    ⭐ 加分項

------------------------------------------------------------------------

# 最推薦優先完成

1.  建立 develop 與 feature 分支流程
2.  所有功能透過 Pull Request 合併
3.  使用 GitHub Issues 管理 Bug 與待辦
4.  建立 GitHub Project（Kanban）
5.  發布 v1.0 Release
6.  完善 README
7.  （加分）GitHub Actions 自動部署

完成以上內容後，專案將更接近一般軟體工程團隊的 Git
管控流程，也能在畢業專題中充分展現團隊協作與版本控制能力。
