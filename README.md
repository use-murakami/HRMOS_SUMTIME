# 勤怠・工数突き合わせ自動通知システム

HRMOS勤怠の勤怠データと自社工数管理システムの稼働実績を週次で突き合わせ、差異が閾値（30分）を超える社員を検出し、Microsoft Teams で通知するシステム。

## 技術スタック

- Python 3.12
- GCP（Cloud Functions / Cloud Scheduler / BigQuery / Secret Manager）
- HRMOS勤怠 REST API
- Microsoft Teams（Power Automate Workflows Webhook）

## 前提条件

- Python 3.12 以上
- Git
- Google Cloud SDK（gcloud CLI）

## 別PCでの環境構築手順

### 1. リポジトリのクローン

```bash
git clone https://github.com/<your-org>/HRMOS_SUMTIME.git
cd HRMOS_SUMTIME
```

### 2. Python 仮想環境の作成

```bash
python -m venv .venv
```

有効化:

```bash
# Windows（PowerShell）
.venv\Scripts\Activate.ps1

# Windows（コマンドプロンプト）
.venv\Scripts\activate.bat

# Windows（Git Bash / WSL）
source .venv/Scripts/activate

# macOS / Linux
source .venv/bin/activate
```

### 3. 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

### 4. 環境変数の設定

`.env.example` を `.env` にコピーし、各値を設定する。

```bash
cp .env.example .env
```

設定が必要な項目:

| 変数名 | 説明 |
|---|---|
| `HRMOS_SECRET_KEY` | HRMOS勤怠 API のシークレットキー |
| `TEAMS_WEBHOOK_URL` | Teams Power Automate Workflows Webhook URL |
| `GCP_PROJECT_ID` | GCP プロジェクト ID |

> `.env` は `.gitignore` に含まれているため、リポジトリには含まれません。

### 5. GCP の設定

```bash
# Google Cloud SDK の認証
gcloud auth login
gcloud config set project <YOUR_PROJECT_ID>

# アプリケーションデフォルト認証（ローカル実行用）
gcloud auth application-default login
```

### 6. 動作確認

```bash
python -m pytest
```

## ディレクトリ構成

```
HRMOS_SUMTIME/
├── README.md
├── .gitignore
├── .env.example              # 環境変数テンプレート（※未作成）
├── requirements.txt          # 依存パッケージ（※未作成）
├── 勤怠工数突き合わせシステム_仕様書.md
└── 作業記録.md
```

> ※ Phase 2 以降で順次ファイルを追加予定。

## ドキュメント

- [仕様書](勤怠工数突き合わせシステム_仕様書.md)
- [作業記録](作業記録.md)
