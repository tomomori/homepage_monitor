# Copyright (C) 2026 daigo-friends(tomomori)
# SPDX-License-Identifier: GPL-3.0-only

"""
ホームページ死活監視ツール メインプログラム。

処理概要:
1. .env を読み込む
2. urls.tsv を読み込む
3. URLごとに並列でチェックを行う
4. 実行日時、HTTPステータス、応答時間などをCSVログへ記録する
5. 異常時、または「正常メール=yes」の場合にメール通知する

対応する監視方式:
- requests   : 通常のHTTP/HTTPSページ
- basic      : Basic認証付きページ
- playwright : フォームログインやJavaScript描画が必要なページ

実行方法:
    python monitor.py
"""

from __future__ import annotations

import csv
import sys
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from checker import CheckResult, HomepageChecker, UrlSetting, parse_url_setting
from config import AppConfig, load_config
from log_writer import CsvLogWriter
from mailer import Mailer


class HomepageMonitor:
    """
    ホームページ死活監視全体を制御するクラス。

    このクラスは、設定読み込み後の一連の流れをまとめます。
    個別のチェック、メール送信、ログ出力は専用クラスに委譲します。
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.checker = HomepageChecker(config)
        self.mailer = Mailer(config)
        self.log_writer = CsvLogWriter(config)

    def run(self) -> int:
        """
        死活監視を実行する。

        Returns
        -------
        int
            終了コード。全URL正常なら 0、1件でも異常があれば 1。
        """

        try:
            settings = self._load_url_settings(self.config.urls_file)
        except Exception as exc:
            print(f"URL一覧ファイルの読み込みに失敗しました: {exc}", file=sys.stderr)
            return 1

        if not settings:
            print("監視対象URLがありません。", file=sys.stderr)
            return 1

        results = self._check_all(settings)

        for result in results:
            self.log_writer.write(result)
            self._send_mail_if_needed(result)

        self._send_summary_mail(results)

        return 0 if all(result.ok for result in results) else 1

    def _load_url_settings(self, urls_file: Path) -> list[UrlSetting]:
        """
        urls.tsv を読み込み、UrlSetting の一覧を返す。
        """

        settings: list[UrlSetting] = []

        with open(urls_file, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")

            for line_no, row in enumerate(reader, start=2):
                setting = parse_url_setting(row)

                if not setting.enabled:
                    print(f"{line_no}行目は有効フラグが無効のためスキップしました。", file=sys.stderr)
                    continue

                if not setting.title or not setting.url:
                    print(f"{line_no}行目はタイトルまたはURLが空のためスキップしました。", file=sys.stderr)
                    continue

                settings.append(setting)

        return settings

    def _check_all(self, settings: list[UrlSetting]) -> list[CheckResult]:
        """
        複数URLを並列でチェックする。
        """

        results: list[CheckResult] = []

        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            # 各URLチェックをスレッドプールへ投入します。
            # Futureだけでは元の設定情報が分からないため、Future -> UrlSetting の対応を保持します。
            future_map = {executor.submit(self.checker.check, setting): setting for setting in settings}

            # 完了したチェックから順に結果を回収します。
            # as_completed() を使うため、出力順は urls.tsv の順番ではなく完了順になります。
            for future in as_completed(future_map):
                setting = future_map[future]

                try:
                    result = future.result()
                except Exception as exc:
                    print(f"チェック処理中に想定外エラーが発生しました: {setting.title} {exc}", file=sys.stderr)
                    continue

                results.append(result)
                status = "OK" if result.ok else "NG"
                print(f"[{status}] {result.title} {result.url} {result.message}")

        return results

    def _send_mail_if_needed(self, result: CheckResult) -> None:
        """
        条件に応じて監視結果メールを送信する。
        """

        should_send = (not result.ok) or result.send_ok_mail

        if not should_send:
            return

        subject_status = "正常" if result.ok else "異常"
        subject = f"【死活監視 {subject_status}】{result.title}"

        try:
            self.mailer.send(result.mail_addrs, subject, result.detail)
        except Exception as exc:
            print(f"メール送信に失敗しました: {result.title} {exc}", file=sys.stderr)
            try:
                self.log_writer.write_mail_error(result, exc)
            except Exception as log_exc:
                print(f"メール送信エラーのログ出力に失敗しました: {result.title} {log_exc}", file=sys.stderr)

    def _send_summary_mail(self, results: list[CheckResult]) -> None:
        """
        全監視結果をまとめたサマリーメールを送信する。
        """

        if not self.config.summary_mail_enabled:
            return

        if not self.config.summary_mail_addrs:
            print("サマリーメールの宛先が未設定のため送信しません。", file=sys.stderr)
            return

        ok_count = sum(1 for result in results if result.ok)
        ng_count = len(results) - ok_count
        subject = f"【死活監視 サマリー】正常{ok_count}件 / 異常{ng_count}件"
        body = self._build_summary_mail_body(results, ok_count, ng_count)

        try:
            self.mailer.send(self.config.summary_mail_addrs, subject, body)
        except Exception as exc:
            print(f"サマリーメール送信に失敗しました: {exc}", file=sys.stderr)

    def _build_summary_mail_body(self, results: list[CheckResult], ok_count: int, ng_count: int) -> str:
        """
        サマリーメール本文を作成する。
        """

        lines = [
            "死活監視の全結果サマリーです。",
            "",
            f"合計: {len(results)}件",
            f"正常: {ok_count}件",
            f"異常: {ng_count}件",
            "",
            "結果一覧:",
        ]

        for result in results:
            status = "正常" if result.ok else "異常"
            status_code = result.status_code if result.status_code is not None else ""
            elapsed_ms = result.elapsed_ms if result.elapsed_ms is not None else ""
            lines.append(
                f"- [{status}] {result.title} {result.url} "
                f"HTTP={status_code} 分類={result.result_type} 応答時間={elapsed_ms}ms {result.message}"
            )

        return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    コマンドライン引数を解析する。
    """

    parser = argparse.ArgumentParser(description="ホームページ死活監視を実行します。")
    parser.add_argument(
        "urls_file",
        nargs="?",
        help=".env の URLS_FILE の代わりに使うURL一覧TSVファイル",
    )
    parser.add_argument(
        "--urls-file",
        dest="urls_file_option",
        help=".env の URLS_FILE の代わりに使うURL一覧TSVファイル",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    コマンドライン実行時の入口。
    """

    args = parse_args(argv)

    try:
        config = load_config(".env")
    except Exception as exc:
        print(f"設定の読み込みに失敗しました: {exc}", file=sys.stderr)
        return 1

    urls_file = args.urls_file_option or args.urls_file
    if urls_file:
        config = AppConfig(
            urls_file=Path(urls_file),
            log_dir=config.log_dir,
            timeout=config.timeout,
            retry_count=config.retry_count,
            retry_wait_seconds=config.retry_wait_seconds,
            max_workers=config.max_workers,
            playwright_headless=config.playwright_headless,
            smtp_host=config.smtp_host,
            smtp_port=config.smtp_port,
            smtp_user=config.smtp_user,
            smtp_password=config.smtp_password,
            smtp_use_tls=config.smtp_use_tls,
            mail_from=config.mail_from,
            summary_mail_enabled=config.summary_mail_enabled,
            summary_mail_addrs=config.summary_mail_addrs,
        )

    monitor = HomepageMonitor(config)
    return monitor.run()


if __name__ == "__main__":
    sys.exit(main())
