# Teams DM送信 検証手順書

Microsoft Graph API を使って Teams の個人チャット（DM）に Adaptive Card を送信できるか検証するためのガイドです。

---

## 事前準備：Azure Portal でのアプリ登録

### 1. アプリを登録する

1. [Azure Portal](https://portal.azure.com) にグローバル管理者でサインイン
2. 左メニューまたは検索から **「Microsoft Entra ID」** を開く
3. 左メニュー →**「アプリの登録」** → **「新規登録」**
4. 以下を入力して「登録」をクリック:

   | 項目 | 値 |
   |---|---|
   | 名前 | `勤怠工数通知システム-dev`（任意） |
   | サポートされるアカウントの種類 | この組織ディレクトリのみ |
   | リダイレクト URI | 未入力のまま |

### 2. API のアクセス許可を追加する

1. 登録されたアプリの左メニュー → **「API のアクセス許可」**
2. **「アクセス許可の追加」** → **「Microsoft Graph」** → **「アプリケーションの許可」**
3. 以下の3つを検索して追加:

   | 権限名 | 用途 |
   |---|---|
   | `Chat.Create` | 1:1チャットの作成 |
   | `ChatMessage.Send` | チャットへのメッセージ送信 |
   | `User.Read.All` | メールアドレスからユーザーIDを取得 |

4. **「{テナント名} に管理者の同意を与えます」** ボタンをクリック
   - 各権限の「状態」欄が ✓ 緑色になれば完了

### 3. クライアントシークレットを生成する

1. 左メニュー → **「証明書とシークレット」** → **「新しいクライアントシークレット」**
2. 説明: `dev-verify`（任意）、有効期限: 任意
3. 「追加」をクリック
4. **「値」列の文字列をすぐにコピーして控える**（画面を離れると二度と表示されない）

### 4. 必要な情報を控える

| 情報 | 場所 |
|---|---|
| **テナントID** | アプリの「概要」→「ディレクトリ（テナント）ID」 |
| **クライアントID** | アプリの「概要」→「アプリケーション（クライアント）ID」 |
| **クライアントシークレット** | 上記手順3でコピーした値 |

---

## スクリプトの実行

### 依存ライブラリのインストール

```bash
pip install requests
```

### 実行コマンド

```bash
cd C:\Users\村上勇治\Documents\Claude\HRMOS_SUMTIME

python tools\verify_teams_dm.py \
  --tenant-id   "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" \
  --client-id   "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" \
  --client-secret "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
  --target-email  "y-murakami@use-eng.co.jp"
```

> ※ `--target-email` には最初は **自分のメールアドレス** を指定して動作確認してください。

---

## 期待される出力

```
============================================================
  Graph API Teams DM 送信検証
============================================================
  対象: y-murakami@use-eng.co.jp

[Step 1] アクセストークン取得...
[Step 1] ✓ トークン取得成功（expires_in: 3599秒）

[Step 2] 対象ユーザー情報取得: y-murakami@use-eng.co.jp
[Step 2] ✓ ユーザーID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
[Step 2]   表示名: 村上 勇治

[Step 3] サービスプリンシパルID取得...
[Step 3] ✓ SP ID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
[Step 3]   アプリ名: 勤怠工数通知システム-dev

[Step 4] 1:1チャット作成...
[Step 4] ✓ チャットID: 19:xxxxxxxx@unq.gbl.spaces

[Step 5] テキストメッセージ送信...
[Step 5] ✓ 送信成功（message-id: xxxxxxxxxxxxxxxx）

[Step 6] Adaptive Card送信（本番想定フォーマット）...
[Step 6] ✓ 送信成功（message-id: xxxxxxxxxxxxxxxx）

============================================================
  検証結果サマリー
============================================================
  Step 1 トークン取得: ✓ 成功
  Step 2 ユーザーID取得: ✓ 成功（村上 勇治）
  Step 3 SP ID取得: ✓ 成功
  Step 4 チャット作成: ✓ 成功
  Step 5 テキスト送信: ✓ 成功
  Step 6 Adaptive Card送信: ✓ 成功

  全6ステップ: 成功 ✓
  → Teams DM送信（Graph API）は実装可能です

  TeamsアプリでDMを確認してください。
  テキストメッセージとAdaptive Cardの2件が届いているはずです。
```

---

## よくあるエラーと対処法

### HTTP 403 / Authorization_RequestDenied

```
[Step 2] ✗ HTTP 403
[Step 2]   エラーコード: Authorization_RequestDenied
```

**原因:** API権限の付与または管理者同意が未完了  
**対処:** Azure Portal → アプリ → API のアクセス許可 → 「管理者の同意を与えます」を再実行

---

### HTTP 401 / InvalidAuthenticationToken

```
[Step 1] ✗ HTTP 401
```

**原因:** テナントID・クライアントID・シークレットのいずれかが誤り  
**対処:** Azure Portal の「概要」ページで各IDを再確認

---

### HTTP 404（Step 2 ユーザー取得）

```
[Step 2] ✗ HTTP 404
```

**原因:** `--target-email` のアドレスがテナントに存在しない  
**対処:** メールアドレスのスペルを確認。Azure Portal → ユーザー で存在確認

---

### Step 4 でチャット作成失敗

**原因:** アプリのサービスプリンシパルが「エンタープライズアプリケーション」として登録されていない場合がある  
**対処:** Azure Portal → Microsoft Entra ID → エンタープライズアプリケーション で `appId` を検索して確認

---

## 検証後の対応

### ✓ 成功した場合

1. クライアントシークレットを **Secret Manager** に登録する準備をする
   - `azure-tenant-id`
   - `azure-client-id`
   - `azure-client-secret`
2. アプリ名を `勤怠工数通知システム-dev` → `勤怠工数通知システム` に変更（任意）
3. Phase 3（Cloud Functions 実装）に進む

### ✗ 失敗した場合

エラーメッセージをそのまま作業記録に残し、次回の確認事項として記録する。

---

## 注意事項

- クライアントシークレットはコマンド履歴に残るため、検証後はシェル履歴のクリアを推奨
- テスト完了後、不要であれば `勤怠工数通知システム-dev` アプリは削除可能（本番実装時に改めて登録）
- `ChatMessage.Send` はテナント内の全ユーザーへの送信権限を持つため、シークレットの厳重管理を徹底すること
