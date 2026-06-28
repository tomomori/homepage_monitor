# Copyright (C) 2026 daigo-friends(tomomori)
# SPDX-License-Identifier: GPL-3.0-only

"""
ホームページ死活監視ツールの設定読み込みモジュール。

このファイルでは、.env ファイルおよびOS環境変数を読み込み、
プログラム全体で使用する設定値を AppConfig としてまとめます。

.env を使う理由:
- SMTPパスワードなどの秘密情報をソースコードから分離できる
- Git管理対象から .env を除外しやすい
- 本番環境、検証環境、開発PCごとに設定を変えやすい

設定ファイルの考え方:
- .env.example : Git管理するサンプル設定
- .env         : 実際の設定。Git管理しない

認証ID方式について:
- urls.tsv にはパスワードそのものを書かず、「認証ID」だけを書きます
- 例: 認証IDが DJANGO_ADMIN の場合、.env には以下を書きます
    DJANGO_ADMIN_USER=admin
    DJANGO_ADMIN_PASSWORD=secret
- プログラムは 認証ID + _USER / _PASSWORD という名前で環境変数を参照します
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class AppConfig:
    """
    アプリケーション全体の設定値を保持するクラス。

    Attributes
    ----------
    urls_file : Path
        監視対象URL一覧ファイル。通常は urls.tsv。
    log_dir : Path
        CSVログの出力先ディレクトリ。
    timeout : int
        HTTPアクセスのタイムアウト秒数。
    retry_count : int
        異常時のリトライ回数。2なら「初回 + 2回リトライ」。
    retry_wait_seconds : int
        リトライ前に待機する秒数。
    max_workers : int
        並列処理数。
    playwright_headless : bool
        Playwright方式でブラウザをヘッドレス実行するかどうか。
    smtp_host : str
        SMTPサーバー名。
    smtp_port : int
        SMTPポート番号。STARTTLSなら一般的に587。
    smtp_user : str
        SMTP認証ユーザー。空の場合は認証なしとして扱います。
    smtp_password : str
        SMTP認証パスワード。
    smtp_use_tls : bool
        STARTTLSを使用するかどうか。
    mail_from : str
        送信元メールアドレス。
    summary_mail_enabled : bool
        全結果をまとめたサマリーメールを送信するかどうか。
    summary_mail_addrs : list[str]
        サマリーメールの宛先メールアドレス一覧。
    """

    urls_file: Path
    log_dir: Path
    timeout: int
    retry_count: int
    retry_wait_seconds: int
    max_workers: int
    playwright_headless: bool
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_use_tls: bool
    mail_from: str
    summary_mail_enabled: bool
    summary_mail_addrs: list[str]


def _get_str(name: str, default: str = "") -> str:
    """
    環境変数を文字列として取得する。

    Parameters
    ----------
    name : str
        環境変数名。
    default : str
        環境変数が未設定の場合の既定値。

    Returns
    -------
    str
        前後の空白を除去した文字列。
    """

    return os.getenv(name, default).strip()


def _get_int(name: str, default: int) -> int:
    """
    環境変数を int として取得する。

    数値に変換できない値が入っていた場合は ValueError を発生させます。
    設定ミスに早く気付けるよう、あえて握りつぶしません。
    """

    return int(_get_str(name, str(default)))


def _get_bool(name: str, default: bool = False) -> bool:
    """
    環境変数を bool として取得する。

    yes / true / 1 / on / y を True と判断します。
    それ以外は False と判断します。
    """

    default_text = "yes" if default else "no"
    value = _get_str(name, default_text)
    return value.lower() in ("yes", "true", "1", "on", "y")


def _get_csv_list(name: str) -> list[str]:
    """
    カンマ区切りの環境変数を文字列リストとして取得する。
    """

    return [
        value.strip()
        for value in _get_str(name, "").split(",")
        if value.strip()
    ]


def get_auth_value(auth_id: str, suffix: str) -> str:
    """
    認証ID方式で .env / 環境変数から認証情報を取得する。

    Parameters
    ----------
    auth_id : str
        urls.tsv の「認証ID」列に書いた値。
        例: DJANGO_ADMIN
    suffix : str
        取得したい項目名。
        例: USER, PASSWORD

    Returns
    -------
    str
        環境変数の値。未設定の場合は空文字。

    Examples
    --------
    auth_id が "DJANGO_ADMIN"、suffix が "USER" の場合、
    DJANGO_ADMIN_USER という環境変数を参照します。
    """

    auth_id = (auth_id or "").strip()
    suffix = (suffix or "").strip().upper()

    if not auth_id or not suffix:
        return ""

    return _get_str(f"{auth_id}_{suffix}", "")


def load_config(env_file: str | Path = ".env") -> AppConfig:
    """
    .env と環境変数を読み込み、AppConfig として返す。

    Notes
    -----
    .env が存在しない場合でも、OS環境変数が設定されていれば動作します。
    LinuxサーバーやDockerで環境変数だけを渡す運用にも対応できます。
    """

    # .env がある場合は読み込みます。
    # override=False のため、OS側の環境変数が既に存在する場合はそちらを優先します。
    load_dotenv(dotenv_path=env_file, override=False)

    smtp_user = _get_str("SMTP_USER", "")
    mail_from = _get_str("MAIL_FROM", "") or smtp_user

    return AppConfig(
        urls_file=Path(_get_str("URLS_FILE", "urls.tsv")),
        log_dir=Path(_get_str("LOG_DIR", "logs")),
        timeout=_get_int("TIMEOUT", 15),
        retry_count=_get_int("RETRY_COUNT", 1),
        retry_wait_seconds=_get_int("RETRY_WAIT_SECONDS", 3),
        max_workers=_get_int("MAX_WORKERS", 5),
        playwright_headless=_get_bool("PLAYWRIGHT_HEADLESS", True),
        smtp_host=_get_str("SMTP_HOST", ""),
        smtp_port=_get_int("SMTP_PORT", 587),
        smtp_user=smtp_user,
        smtp_password=_get_str("SMTP_PASSWORD", ""),
        smtp_use_tls=_get_bool("SMTP_USE_TLS", True),
        mail_from=mail_from,
        summary_mail_enabled=_get_bool("SUMMARY_MAIL_ENABLED", False),
        summary_mail_addrs=_get_csv_list("SUMMARY_MAIL_TO"),
    )
