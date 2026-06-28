# Copyright (C) 2026 daigo-friends(tomomori)
# SPDX-License-Identifier: GPL-3.0-only

"""
CSVログ出力モジュール。

監視結果を日付別CSVファイルに追記します。
Excel等で開きやすいように、UTF-8 BOM付きで作成します。
"""

from __future__ import annotations

import csv
from pathlib import Path

from checker import CheckResult
from config import AppConfig


class CsvLogWriter:
    """
    死活監視結果をCSVに出力するクラス。
    """

    def __init__(self, config: AppConfig) -> None:
        """
        CsvLogWriter を初期化する。

        Parameters
        ----------
        config : AppConfig
            ログ出力先ディレクトリなどの設定。
        """

        self.config = config
        self.config.log_dir.mkdir(parents=True, exist_ok=True)

    def write(self, result: CheckResult) -> None:
        """
        監視結果をCSVログに1行追記する。

        Parameters
        ----------
        result : CheckResult
            監視結果。
        """

        log_file = self._get_log_file(result)
        is_new_file = not log_file.exists()

        # utf-8-sig にすることで、Excelで開いたときの文字化けを避けやすくします。
        with open(log_file, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)

            # 新規ファイルの場合のみヘッダー行を書き込みます。
            if is_new_file:
                writer.writerow([
                    "日時",
                    "状態",
                    "タイトル",
                    "URL",
                    "HTTPステータス",
                    "結果",
                    "分類",
                    "メッセージ",
                    "応答時間(ms)",
                ])

            writer.writerow([
                result.checked_at.strftime("%Y-%m-%d %H:%M:%S"),
                "正常" if result.ok else "異常",
                result.title,
                result.url,
                result.status_code if result.status_code is not None else "",
                "OK" if result.ok else "NG",
                result.result_type,
                result.message,
                result.elapsed_ms if result.elapsed_ms is not None else "",
            ])

    def write_mail_error(self, result: CheckResult, error: Exception) -> None:
        """
        メール送信エラーをCSVログに1行追記する。
        """

        log_file = self._get_log_file(result)
        is_new_file = not log_file.exists()

        with open(log_file, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)

            if is_new_file:
                writer.writerow([
                    "日時",
                    "状態",
                    "タイトル",
                    "URL",
                    "HTTPステータス",
                    "結果",
                    "分類",
                    "メッセージ",
                    "応答時間(ms)",
                ])

            writer.writerow([
                result.checked_at.strftime("%Y-%m-%d %H:%M:%S"),
                "異常",
                result.title,
                result.url,
                "",
                "NG",
                "MAIL_SEND_ERROR",
                f"メール送信に失敗しました: {error}",
                "",
            ])

    def _get_log_file(self, result: CheckResult) -> Path:
        """
        監視日時に対応するログファイルパスを返す。
        """

        file_name = result.checked_at.strftime("monitor_%Y%m%d.csv")
        return self.config.log_dir / file_name
