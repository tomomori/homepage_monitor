# Copyright (C) 2026 daigo-friends(tomomori)
# SPDX-License-Identifier: GPL-3.0-only

"""
ホームページ死活監視のチェック処理モジュール。

このモジュールでは、urls.tsv の1行分を受け取り、対象URLにアクセスして
正常/異常を判定します。

対応する監視方式:
- requests   : 通常のHTTP/HTTPSページ
- basic      : Basic認証付きページ
- playwright : JavaScriptやフォームログインが必要なページ

Playwrightについて:
- Playwrightは追加ライブラリです
- 通常のHTTP監視だけならインストール不要です
- playwright方式の行がある場合のみ必要になります
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests
from requests import Response
from requests.exceptions import ConnectionError, RequestException, SSLError, Timeout

from config import AppConfig, get_auth_value


@dataclass
class UrlSetting:
    """
    urls.tsv の1行分を表すクラス。

    Attributes
    ----------
    enabled : bool
        True の場合のみ監視対象として扱います。
    title : str
        監視対象の表示名。メール件名やログに出力します。
    url : str
        監視対象URL。
    is_300_error : bool
        True の場合、HTTP 300番台を異常として扱います。
    send_ok_mail : bool
        True の場合、正常時にもメール送信します。
    mail_addrs : list[str]
        通知先メールアドレス一覧。
    monitor_type : str
        監視方式。requests / basic / playwright。
    login_url : str
        playwright方式でログイン画面を開くURL。
    basic_auth_id : str
        Basic認証用の認証ID。
        例: BASIC_SAMPLE と書くと BASIC_SAMPLE_USER / BASIC_SAMPLE_PASSWORD を参照します。
    login_auth_id : str
        Playwright方式でログイン画面に入力する認証ID。
        例: DJANGO_ADMIN と書くと DJANGO_ADMIN_USER / DJANGO_ADMIN_PASSWORD を参照します。
    check_text : str
        レスポンス本文やログイン後画面に含まれているべき文字列。
        空の場合はHTTPステータス中心で判定します。
    username_selector : str
        Playwrightでユーザー名入力欄を探すためのCSSセレクタ。
    password_selector : str
        Playwrightでパスワード入力欄を探すためのCSSセレクタ。
    submit_selector : str
        Playwrightでログインボタンを探すためのCSSセレクタ。
    """

    enabled: bool
    title: str
    url: str
    is_300_error: bool
    send_ok_mail: bool
    mail_addrs: list[str]
    monitor_type: str = "requests"
    login_url: str = ""
    basic_auth_id: str = ""
    login_auth_id: str = ""
    check_text: str = ""
    username_selector: str = "input[name='username']"
    password_selector: str = "input[name='password']"
    submit_selector: str = "button[type='submit'], input[type='submit']"


@dataclass
class CheckResult:
    """
    URLチェック結果を表すクラス。

    Attributes
    ----------
    checked_at : datetime
        チェックを実行した日時。
    title : str
        監視対象のタイトル。
    url : str
        監視対象URL。
    ok : bool
        正常なら True、異常なら False。
    status_code : Optional[int]
        HTTPステータスコード。接続失敗などで取得できない場合は None。
    result_type : str
        結果分類。OK / HTTP_ERROR / TIMEOUT / TEXT_NOT_FOUND など。
    message : str
        人間が読める結果メッセージ。
    elapsed_ms : Optional[int]
        応答時間。取得できた場合のみ値が入ります。
    mail_addrs : list[str]
        この結果を通知する宛先。
    send_ok_mail : bool
        正常時にもメール通知するかどうか。
    detail : str
        メール本文として利用できる詳細情報。
    """

    checked_at: datetime
    title: str
    url: str
    ok: bool
    status_code: Optional[int]
    result_type: str
    message: str
    elapsed_ms: Optional[int]
    mail_addrs: list[str]
    send_ok_mail: bool
    detail: str


def to_bool(value: str) -> bool:
    """
    urls.tsv 上の yes/no 等の文字列を bool に変換する。
    """

    return str(value).strip().lower() in ("yes", "true", "1", "on", "y")


def row_text(row: dict[str, str], key: str, default: str = "") -> str:
    """
    TSV上で省略されたセルは None になるため、文字列として安全に扱う。
    """

    value = row.get(key)
    if value is None:
        return default
    return str(value)


def parse_url_setting(row: dict[str, str]) -> UrlSetting:
    """
    urls.tsv から読み込んだ1行を UrlSetting に変換する。

    古いurls.tsvとの互換性を少しだけ持たせるため、追加列が存在しない場合は
    既定値で requests 監視として扱います。
    """

    mail_addrs = [
        addr.strip()
        for addr in row_text(row, "メールアドレス").split(",")
        if addr.strip()
    ]

    return UrlSetting(
        enabled=to_bool(row_text(row, "有効", "yes")),
        title=row_text(row, "タイトル").strip(),
        url=row_text(row, "URL").strip(),
        is_300_error=to_bool(row_text(row, "300エラー", "no")),
        send_ok_mail=to_bool(row_text(row, "正常メール", "no")),
        mail_addrs=mail_addrs,
        monitor_type=row_text(row, "監視方式", "requests").strip().lower() or "requests",
        login_url=row_text(row, "ログインURL").strip(),
        basic_auth_id=(row_text(row, "Basic認証ID") or row_text(row, "認証ID")).strip(),
        login_auth_id=(row_text(row, "ログイン認証ID") or row_text(row, "認証ID")).strip(),
        check_text=row_text(row, "確認文字列").strip(),
        username_selector=row_text(row, "ユーザー名セレクタ").strip() or "input[name='username']",
        password_selector=row_text(row, "パスワードセレクタ").strip() or "input[name='password']",
        submit_selector=row_text(row, "送信ボタンセレクタ").strip() or "button[type='submit'], input[type='submit']",
    )


class HomepageChecker:
    """
    ホームページ死活監視を行うクラス。

    監視方式に応じて、requests / Basic認証 / Playwright の処理へ振り分けます。
    リトライ処理もこのクラス内で行います。
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def check(self, setting: UrlSetting) -> CheckResult:
        """
        URLを1件チェックする。

        retry_count=2 の場合、初回 + 再試行2回 = 最大3回実行します。
        """

        last_result: CheckResult | None = None

        for attempt in range(self.config.retry_count + 1):
            result = self._check_once(setting, attempt + 1)

            if result.ok:
                return result

            last_result = result

            if attempt < self.config.retry_count:
                time.sleep(self.config.retry_wait_seconds)

        assert last_result is not None
        return last_result

    def _check_once(self, setting: UrlSetting, attempt_no: int) -> CheckResult:
        """
        監視方式に応じて1回だけチェックする。
        """

        if setting.monitor_type == "requests":
            return self._check_requests(setting, attempt_no)

        if setting.monitor_type == "basic":
            return self._check_basic(setting, attempt_no)

        if setting.monitor_type == "playwright":
            return self._check_playwright(setting, attempt_no)

        checked_at = datetime.now()
        return self._build_plain_result(
            setting=setting,
            checked_at=checked_at,
            ok=False,
            status_code=None,
            result_type="UNKNOWN_MONITOR_TYPE",
            message=f"未対応の監視方式です: {setting.monitor_type}",
            elapsed_ms=None,
            attempt_no=attempt_no,
        )

    def _check_requests(self, setting: UrlSetting, attempt_no: int) -> CheckResult:
        """
        通常のHTTP/HTTPSページを requests でチェックする。
        """

        return self._check_by_requests_common(setting, attempt_no, auth=None)

    def _check_basic(self, setting: UrlSetting, attempt_no: int) -> CheckResult:
        """
        Basic認証付きページを requests でチェックする。

        urls.tsv の「Basic認証ID」を使って、.env から以下を取得します。
        例: Basic認証ID BASIC_SAMPLE の場合
            BASIC_SAMPLE_USER
            BASIC_SAMPLE_PASSWORD
        """

        username = get_auth_value(setting.basic_auth_id, "USER")
        password = get_auth_value(setting.basic_auth_id, "PASSWORD")

        if not username or not password:
            checked_at = datetime.now()
            return self._build_plain_result(
                setting=setting,
                checked_at=checked_at,
                ok=False,
                status_code=None,
                result_type="AUTH_SETTING_ERROR",
                message=f"Basic認証情報が不足しています。Basic認証ID={setting.basic_auth_id}",
                elapsed_ms=None,
                attempt_no=attempt_no,
            )

        return self._check_by_requests_common(setting, attempt_no, auth=(username, password))

    def _check_by_requests_common(self, setting: UrlSetting, attempt_no: int, auth: tuple[str, str] | None) -> CheckResult:
        """
        requests方式とBasic認証方式で共通利用するHTTPチェック処理。
        """

        checked_at = datetime.now()
        start_time = time.perf_counter()

        try:
            response = requests.get(
                setting.url,
                timeout=self.config.timeout,
                allow_redirects=not setting.is_300_error,
                auth=auth,
                headers={"User-Agent": "Homepage-Monitor/1.0 (+Python requests)"},
            )
            self._fix_response_encoding(response)

            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            return self._build_http_result(setting, checked_at, response, elapsed_ms, attempt_no)

        except Timeout as exc:
            return self._build_exception_result(setting, checked_at, "TIMEOUT", "タイムアウト", exc, attempt_no)
        except SSLError as exc:
            return self._build_exception_result(setting, checked_at, "SSL_ERROR", "SSLエラー", exc, attempt_no)
        except ConnectionError as exc:
            return self._build_exception_result(setting, checked_at, "CONNECTION_ERROR", "接続エラー", exc, attempt_no)
        except RequestException as exc:
            return self._build_exception_result(setting, checked_at, "REQUEST_ERROR", "HTTPリクエストエラー", exc, attempt_no)
        except Exception as exc:
            return self._build_exception_result(setting, checked_at, "UNKNOWN_ERROR", "想定外エラー", exc, attempt_no)

    def _check_playwright(self, setting: UrlSetting, attempt_no: int) -> CheckResult:
        """
        Playwrightを使って、ログインが必要なページをチェックする。

        処理の流れ:
        1. ログインURLを開く
        2. ユーザー名とパスワードを入力する
        3. ログインボタンを押す
        4. 監視対象URLを開く
        5. 確認文字列があれば、その文字列が画面内にあるか確認する

        注意:
        - MFA/TOTPはこのサンプルでは対応しません
        - サイトごとに入力欄のセレクタが異なる場合があります
        - その場合は urls.tsv のセレクタ列を調整してください
        """

        checked_at = datetime.now()
        start_time = time.perf_counter()

        username = get_auth_value(setting.login_auth_id, "USER")
        password = get_auth_value(setting.login_auth_id, "PASSWORD")
        basic_username = get_auth_value(setting.basic_auth_id, "USER")
        basic_password = get_auth_value(setting.basic_auth_id, "PASSWORD")

        if not setting.login_url:
            return self._build_plain_result(setting, checked_at, False, None, "LOGIN_URL_EMPTY", "ログインURLが未設定です", None, attempt_no)

        if not username or not password:
            return self._build_plain_result(
                setting, checked_at, False, None, "AUTH_SETTING_ERROR",
                f"Playwrightログイン認証情報が不足しています。ログイン認証ID={setting.login_auth_id}", None, attempt_no
            )

        if setting.basic_auth_id and (not basic_username or not basic_password):
            return self._build_plain_result(
                setting, checked_at, False, None, "BASIC_AUTH_SETTING_ERROR",
                f"Playwright用Basic認証情報が不足しています。Basic認証ID={setting.basic_auth_id}", None, attempt_no
            )

        try:
            # playwrightを使わない環境でも通常監視が動くよう、ここで遅延インポートします。
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            return self._build_exception_result(
                setting, checked_at, "PLAYWRIGHT_IMPORT_ERROR",
                "Playwrightがインストールされていない、またはブラウザ未導入です",
                exc, attempt_no,
            )

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.config.playwright_headless)
                context_options = {}
                if setting.basic_auth_id:
                    context_options["http_credentials"] = {
                        "username": basic_username,
                        "password": basic_password,
                    }
                context = browser.new_context(**context_options)
                page = context.new_page()
                page.set_default_timeout(self.config.timeout * 1000)

                # ログイン画面へ移動します。
                login_response = page.goto(setting.login_url, wait_until="domcontentloaded")

                # ユーザー名、パスワードを入力します。
                page.fill(setting.username_selector, username)
                page.fill(setting.password_selector, password)

                # ログインボタンをクリックし、画面遷移またはネットワーク待ちを行います。
                page.click(setting.submit_selector)
                page.wait_for_load_state("networkidle")

                # ログイン後に監視対象URLへ移動します。
                target_response = page.goto(setting.url, wait_until="networkidle")
                status_code = target_response.status if target_response else None

                body_text = page.locator("body").inner_text(timeout=self.config.timeout * 1000)
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                context.close()
                browser.close()

                if status_code is not None and not self._is_status_ok(status_code, setting):
                    return self._build_plain_result(
                        setting, checked_at, False, status_code, "HTTP_ERROR",
                        f"HTTPステータスが異常です: {status_code}", elapsed_ms, attempt_no,
                    )

                if setting.check_text and setting.check_text not in body_text:
                    return self._build_plain_result(
                        setting, checked_at, False, status_code, "TEXT_NOT_FOUND",
                        f"確認文字列が見つかりません: {setting.check_text}", elapsed_ms, attempt_no,
                    )

                return self._build_plain_result(
                    setting, checked_at, True, status_code, "OK", "正常", elapsed_ms, attempt_no,
                )

        except PlaywrightTimeoutError as exc:
            return self._build_exception_result(setting, checked_at, "PLAYWRIGHT_TIMEOUT", "Playwrightタイムアウト", exc, attempt_no)
        except Exception as exc:
            return self._build_exception_result(setting, checked_at, "PLAYWRIGHT_ERROR", "Playwright実行エラー", exc, attempt_no)

    def _is_status_ok(self, status_code: int, setting: UrlSetting) -> bool:
        """
        HTTPステータスコードが正常扱いかどうかを判定する。
        """

        if 200 <= status_code < 300:
            return True
        if 300 <= status_code < 400:
            return not setting.is_300_error
        return False

    def _fix_response_encoding(self, response: Response) -> None:
        """
        HTTPヘッダーにcharsetが無いHTMLで日本語が文字化けする場合に補正する。
        """

        apparent_encoding = response.apparent_encoding
        if response.encoding and response.encoding.lower() != "iso-8859-1":
            return
        if apparent_encoding:
            response.encoding = apparent_encoding

    def _build_http_result(
        self,
        setting: UrlSetting,
        checked_at: datetime,
        response: Response,
        elapsed_ms: int,
        attempt_no: int,
    ) -> CheckResult:
        """
        requests の Response から CheckResult を作成する。
        """

        status_code = response.status_code

        if self._is_status_ok(status_code, setting):
            if setting.check_text and setting.check_text not in response.text:
                return self._build_plain_result(
                    setting, checked_at, False, status_code, "TEXT_NOT_FOUND",
                    f"確認文字列が見つかりません: {setting.check_text}", elapsed_ms, attempt_no,
                )
            return self._build_plain_result(setting, checked_at, True, status_code, "OK", "正常", elapsed_ms, attempt_no)

        if 300 <= status_code < 400:
            return self._build_plain_result(setting, checked_at, False, status_code, "REDIRECT", "300番台レスポンス", elapsed_ms, attempt_no)

        return self._build_plain_result(setting, checked_at, False, status_code, "HTTP_ERROR", f"HTTPエラー: {status_code}", elapsed_ms, attempt_no)

    def _build_plain_result(
        self,
        setting: UrlSetting,
        checked_at: datetime,
        ok: bool,
        status_code: Optional[int],
        result_type: str,
        message: str,
        elapsed_ms: Optional[int],
        attempt_no: int,
    ) -> CheckResult:
        """
        通常の結果情報から CheckResult を作成する。
        """

        detail = self._build_detail(
            setting=setting,
            checked_at=checked_at,
            ok=ok,
            status_code=status_code,
            result_type=result_type,
            message=message,
            elapsed_ms=elapsed_ms,
            attempt_no=attempt_no,
            extra="",
        )

        return CheckResult(
            checked_at=checked_at,
            title=setting.title,
            url=setting.url,
            ok=ok,
            status_code=status_code,
            result_type=result_type,
            message=message,
            elapsed_ms=elapsed_ms,
            mail_addrs=setting.mail_addrs,
            send_ok_mail=setting.send_ok_mail,
            detail=detail,
        )

    def _build_exception_result(
        self,
        setting: UrlSetting,
        checked_at: datetime,
        result_type: str,
        message: str,
        exc: Exception,
        attempt_no: int,
    ) -> CheckResult:
        """
        例外から CheckResult を作成する。
        """

        extra = f"例外内容: {exc}\n\n{traceback.format_exc()}"
        detail = self._build_detail(setting, checked_at, False, None, result_type, message, None, attempt_no, extra)

        return CheckResult(
            checked_at=checked_at,
            title=setting.title,
            url=setting.url,
            ok=False,
            status_code=None,
            result_type=result_type,
            message=message,
            elapsed_ms=None,
            mail_addrs=setting.mail_addrs,
            send_ok_mail=setting.send_ok_mail,
            detail=detail,
        )

    def _build_detail(
        self,
        setting: UrlSetting,
        checked_at: datetime,
        ok: bool,
        status_code: Optional[int],
        result_type: str,
        message: str,
        elapsed_ms: Optional[int],
        attempt_no: int,
        extra: str,
    ) -> str:
        """
        メール本文として使用する詳細テキストを作成する。
        """

        lines = [
            "ホームページ死活監視結果",
            "",
            f"日時: {checked_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"タイトル: {setting.title}",
            f"URL: {setting.url}",
            f"監視方式: {setting.monitor_type}",
            f"結果: {'正常' if ok else '異常'}",
            f"分類: {result_type}",
            f"メッセージ: {message}",
            f"HTTPステータス: {status_code if status_code is not None else ''}",
            f"応答時間(ms): {elapsed_ms if elapsed_ms is not None else ''}",
            f"試行回数: {attempt_no}",
        ]

        if setting.check_text:
            lines.append(f"確認文字列: {setting.check_text}")

        if extra:
            lines.extend(["", extra])

        return "\n".join(lines)
