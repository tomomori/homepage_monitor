# ホームページ死活監視ツール

## 概要

`urls.tsv` に記載したURLへアクセスし、HTTPステータス、応答時間、正常/異常をCSVログへ記録します。
異常時、または `urls.tsv` の「正常メール」が `yes` の場合に、指定されたメールアドレスへ結果を通知します。

主な機能は以下です。

- 複数URLの死活監視
- HTTPステータスの記録
- 応答時間の記録
- 300番台レスポンスをエラー扱いにするかどうかをURLごとに指定
- 正常時にもメール通知するかどうかをURLごとに指定
- 通知先メールアドレスをURLごとに指定
- 確認文字列の有無による判定
- Basic認証ページの監視
- Playwrightによるログイン後ページの監視
- 異常時のリトライ
- 並列処理
- CSVログ出力
- `.env` による設定管理
- 認証ID方式によるパスワード分離

## ファイル構成

```text
homepage_monitor/
├── monitor.py                   メインプログラム
├── checker.py                   HTTP / Basic認証 / Playwrightチェック処理
├── mailer.py                    メール送信処理
├── log_writer.py                CSVログ出力処理
├── cleanup_logs.py              古いCSVログの削除処理
├── config.py                    .env / 環境変数の読み込み処理
├── urls.example.tsv             監視対象URL一覧のサンプル。Git管理する
├── urls.tsv                     実運用用の監視対象URL一覧。Git管理しない
├── .env.example                 .env のサンプル
├── .gitignore                   Git管理対象外ファイルの指定
├── requirements.txt             基本依存ライブラリ
├── requirements-playwright.txt  Playwright使用時のみ必要な依存ライブラリ
├── LICENSE                      GNU GPL v3.0 ライセンス本文
├── README.md                    この説明ファイル
└── logs/                        ログ出力先。実行時に自動作成されます
```

## インストール

通常のHTTP監視、Basic認証監視だけであれば以下です。

```bash
pip install -r requirements.txt
```

Playwright方式を使う場合は、追加で以下を実行してください。

```bash
pip install -r requirements-playwright.txt
python -m playwright install chromium
```

LinuxサーバーでPlaywrightの実行に必要なOSパッケージもまとめて入れたい場合は、以下が使える環境もあります。

```bash
python -m playwright install --with-deps chromium
```

## 初期設定ファイルの作成

公開リポジトリでも安全に扱えるよう、実運用用の `.env` と `urls.tsv` はGit管理しません。

まず、サンプルファイルをコピーして実運用用ファイルを作成します。

```bash
cp .env.example .env
cp urls.example.tsv urls.tsv
```

Windows PowerShell の場合は以下です。

```powershell
Copy-Item .env.example .env
Copy-Item urls.example.tsv urls.tsv
```

`.env` と `urls.tsv` の中身を実際の環境に合わせて修正してください。

```ini
URLS_FILE=urls.tsv
LOG_DIR=logs
TIMEOUT=15
RETRY_COUNT=1
RETRY_WAIT_SECONDS=3
MAX_WORKERS=5
PLAYWRIGHT_HEADLESS=yes

SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=user@example.com
SMTP_PASSWORD=password
SMTP_USE_TLS=yes
MAIL_FROM=monitor@example.com

SUMMARY_MAIL_ENABLED=no
SUMMARY_MAIL_TO=admin@example.com
```

`.env` にはSMTPパスワードやログインパスワードなどの秘密情報を記載します。
`urls.tsv` には管理画面URL、顧客サイトURL、通知先メールアドレス、確認文字列など、公開したくない情報が入る可能性があります。
そのため `.gitignore` により、`.env` と `urls.tsv` はGit管理対象外にしています。

## urls.tsv / urls.example.tsv の形式

`urls.example.tsv` はサンプルです。実運用ではコピーして作成した `urls.tsv` を編集します。

`urls.tsv` はタブ区切りファイルです。Excelで編集する場合は、保存形式に注意してください。

```tsv
有効	タイトル	URL	300エラー	正常メール	メールアドレス	監視方式	ログインURL	Basic認証ID	ログイン認証ID	確認文字列	ユーザー名セレクタ	パスワードセレクタ	送信ボタンセレクタ
```

### 各列の意味

| 列名 | 説明 |
|---|---|
| 有効 | `yes` の場合のみ監視対象。`no` の行はクロールせずスキップ |
| タイトル | メール件名やログに出す表示名 |
| URL | 監視対象URL |
| 300エラー | `yes` の場合、301/302などの300番台を異常扱い。`requests` / `basic` 方式ではリダイレクトをたどらず最初の300番台を判定します。`playwright` 方式ではブラウザとしてリダイレクトをたどるため、途中の300番台は異常扱いせず、最終レスポンスで判定します。 |
| 正常メール | `yes` の場合、正常時にもメール通知 |
| メールアドレス | 通知先。カンマ区切りで複数指定可能 |
| 監視方式 | `requests` / `basic` / `playwright` |
| ログインURL | `playwright` 方式でログイン画面を開くURL |
| Basic認証ID | Basic認証用の認証ID。`basic` 方式、または `playwright` 方式でアプリログイン前にBasic認証を通す場合に指定 |
| ログイン認証ID | `playwright` 方式でログイン画面に入力する認証ID。不要なら空欄 |
| 確認文字列 | レスポンス本文またはログイン後画面に含まれているべき文字列 |
| ユーザー名セレクタ | Playwrightでユーザー名入力欄を探すCSSセレクタ |
| パスワードセレクタ | Playwrightでパスワード入力欄を探すCSSセレクタ |
| 送信ボタンセレクタ | Playwrightでログインボタンを探すCSSセレクタ |

## 監視方式

### requests

通常のHTTP/HTTPSページを監視します。

```tsv
yes	自社ホームページ	https://example.com	no	no	admin@example.com	requests				Example Domain
```

`確認文字列` を指定すると、HTTPステータスが正常でも、その文字列が本文に含まれていない場合は異常になります。

### basic

Basic認証付きページを監視します。

`urls.tsv` の例です。

```tsv
yes	Basic認証ページ	https://example.com/private/	no	no	admin@example.com	basic		BASIC_SAMPLE		認証済み
```

`.env` の例です。

```ini
BASIC_SAMPLE_USER=basic_user
BASIC_SAMPLE_PASSWORD=basic_password
```

`Basic認証ID` に `BASIC_SAMPLE` と書くと、プログラムは以下の環境変数を参照します。

```text
BASIC_SAMPLE_USER
BASIC_SAMPLE_PASSWORD
```

### playwright

ログイン操作が必要なページを監視します。MFA/TOTPは対象外です。
動作中のブラウザ画面を見ながら確認したい場合は、`.env` で `PLAYWRIGHT_HEADLESS=no` にしてください。

`urls.tsv` の例です。

```tsv
yes	ログイン後ページ	https://example.com/dashboard/	no	no	admin@example.com	playwright	https://example.com/login/		DJANGO_ADMIN	ダッシュボード	input[name='username']	input[name='password']	button[type='submit']
```

`.env` の例です。

```ini
DJANGO_ADMIN_USER=admin
DJANGO_ADMIN_PASSWORD=admin_password
```

この場合、処理の流れは以下になります。

1. `https://example.com/login/` を開く
2. `input[name='username']` にユーザー名を入力
3. `input[name='password']` にパスワードを入力
4. `button[type='submit']` をクリック
5. `https://example.com/dashboard/` を開く
6. 画面内に `ダッシュボード` が含まれているか確認

Basic認証で保護されたページの先にアプリログイン画面がある場合は、`Basic認証ID` も指定します。

```tsv
yes	Basic認証後ログインページ	https://example.com/secure/dashboard/	no	no	admin@example.com	playwright	https://example.com/secure/login/	BASIC_SAMPLE	DJANGO_ADMIN	ダッシュボード	input[name='username']	input[name='password']	button[type='submit']
```

この場合、Playwrightはまず `BASIC_SAMPLE_USER` / `BASIC_SAMPLE_PASSWORD` をブラウザのBasic認証情報として使い、その後ログイン画面で `DJANGO_ADMIN_USER` / `DJANGO_ADMIN_PASSWORD` を入力します。

## 認証ID方式について

`urls.tsv` には、ユーザー名やパスワードを直接書きません。
代わりに `Basic認証ID` または `ログイン認証ID` だけを書きます。

例えば、`urls.tsv` に以下のように書いた場合です。

```tsv
yes	ログイン後ページ	https://example.com/dashboard/	no	no	admin@example.com	playwright	https://example.com/login/		DJANGO_ADMIN	ダッシュボード	input[name='username']	input[name='password']	button[type='submit']
```

`.env` には以下を書きます。

```ini
DJANGO_ADMIN_USER=admin
DJANGO_ADMIN_PASSWORD=admin_password
```

つまり、`ログイン認証ID` が `DJANGO_ADMIN` の場合、以下の2つが使われます。

```text
DJANGO_ADMIN_USER
DJANGO_ADMIN_PASSWORD
```

この方式により、`urls.tsv` にパスワードを直接書かずに済みます。
ただし、`urls.tsv` にはURLや通知先などの情報が含まれるため、公開リポジトリではGit管理しない方針にしています。

## Git管理の方針

GitHubなどで公開する可能性がある場合は、以下の方針を推奨します。

```text
Git管理する
- monitor.py
- checker.py
- mailer.py
- log_writer.py
- cleanup_logs.py
- config.py
- README.md
- requirements.txt
- requirements-playwright.txt
- LICENSE
- .env.example
- urls.example.tsv
- .gitignore

Git管理しない
- .env
- urls.tsv
- logs/
```

`urls.tsv` にパスワードを書かない設計でも、以下のような情報が含まれる場合があります。

- 管理画面URL
- 社内システムURL
- 顧客サイトURL
- 通知先メールアドレス
- 画面内の確認文字列
- 認証ID名

これらは秘密鍵ではありませんが、公開リポジトリには載せない方が安全です。
そのため、公開用には `urls.example.tsv` のみを含め、実運用用の `urls.tsv` は各環境で作成します。

## 実行

```bash
python monitor.py
```

`.env` の `URLS_FILE` とは別のURL一覧ファイルを使う場合は、実行時引数で指定できます。

```bash
python monitor.py urls.test.tsv
```

または以下でも同じです。

```bash
python monitor.py --urls-file urls.test.tsv
```

## ログ

ログは `logs/monitor_YYYYMMDD.csv` に出力されます。

出力項目は以下です。

```text
日時,状態,タイトル,URL,HTTPステータス,結果,分類,メッセージ,応答時間(ms)
```

`状態` には、人が見て分かりやすいように `正常` または `異常` を出力します。

古いログを削除する場合は `cleanup_logs.py` を使います。

```bash
python cleanup_logs.py --delete-before 2026-06-01
```

上記は2026-06-01より前の `logs/monitor_YYYYMMDD.csv` を削除します。
削除対象だけ確認したい場合は `--dry-run` を付けます。

```bash
python cleanup_logs.py --delete-before 2026-06-01 --dry-run
```

## メール通知

異常時、または `urls.tsv` の `正常メール` が `yes` の場合は、各行の `メールアドレス` 宛てに個別メールを送信します。

処理全体の最後に、正常・異常を含む全結果をまとめたサマリーメールも送信できます。

```ini
SUMMARY_MAIL_ENABLED=yes
SUMMARY_MAIL_TO=admin@example.com,staff@example.com
```

`SUMMARY_MAIL_ENABLED=no` の場合、サマリーメールは送信しません。個別メール送信の動作には影響しません。

## cron例

5分ごとに実行する例です。

```cron
*/5 * * * * cd /path/to/homepage_monitor && /usr/bin/python3 monitor.py
```

## Windowsタスクスケジューラ例

プログラム/script:

```text
python
```

引数:

```text
monitor.py
```

開始場所:

```text
C:\path\to\homepage_monitor
```

## 注意点

- MFA/TOTPはこのサンプルでは対応していません
- Playwright方式は通常のHTTP監視より重いです
- Playwright方式の監視対象が多い場合、`MAX_WORKERS` は小さめから始めてください
- ログインフォームのHTML構造によっては、CSSセレクタの調整が必要です
- `.env` はGitに登録しないでください

## ライセンス

このプロジェクトは GNU General Public License v3.0 の下で配布されます。
詳細は [LICENSE](LICENSE) を参照してください。

Copyright (C) 2026 daigo-friends(tomomori)
