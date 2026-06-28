# Copyright (C) 2026 daigo-friends(tomomori)
# SPDX-License-Identifier: GPL-3.0-only

"""
古い監視ログを削除するスクリプト。

logs/monitor_YYYYMMDD.csv 形式のログを対象に、指定日より前のファイルを削除します。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from config import load_config


LOG_FILE_PREFIX = "monitor_"
LOG_FILE_SUFFIX = ".csv"
LOG_DATE_FORMAT = "%Y%m%d"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    コマンドライン引数を解析する。
    """

    parser = argparse.ArgumentParser(description="指定日より前の監視ログを削除します。")
    parser.add_argument(
        "--delete-before",
        required=True,
        type=parse_delete_before_date,
        metavar="YYYY-MM-DD",
        help="この日付より前のログを削除します。例: 2026-06-01",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help=".env の LOG_DIR の代わりに使うログディレクトリ。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="削除せず、削除対象ファイルだけ表示します。",
    )
    return parser.parse_args(argv)


def parse_delete_before_date(value: str) -> date:
    """
    YYYY-MM-DD 形式の日付引数を date に変換する。
    """

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("日付は YYYY-MM-DD 形式で指定してください。") from exc


def parse_log_date(path: Path) -> date | None:
    """
    monitor_YYYYMMDD.csv 形式のファイル名から日付を取り出す。
    """

    name = path.name
    if not name.startswith(LOG_FILE_PREFIX) or not name.endswith(LOG_FILE_SUFFIX):
        return None

    date_text = name[len(LOG_FILE_PREFIX):-len(LOG_FILE_SUFFIX)]
    try:
        return datetime.strptime(date_text, LOG_DATE_FORMAT).date()
    except ValueError:
        return None


def find_logs_before(log_dir: Path, delete_before: date) -> list[Path]:
    """
    指定日より前のログファイル一覧を返す。
    """

    old_logs: list[Path] = []

    if not log_dir.exists():
        return old_logs

    for path in log_dir.iterdir():
        if not path.is_file():
            continue

        log_date = parse_log_date(path)
        if log_date is None:
            continue

        if log_date < delete_before:
            old_logs.append(path)

    return sorted(old_logs)


def delete_logs_before(log_dir: Path, delete_before: date, dry_run: bool = False) -> int:
    """
    指定日より前のログファイルを削除し、対象件数を返す。
    """

    old_logs = find_logs_before(log_dir, delete_before)

    for path in old_logs:
        if dry_run:
            print(f"削除対象: {path}")
        else:
            path.unlink()
            print(f"削除しました: {path}")

    if not old_logs:
        print("削除対象のログはありません。")

    return len(old_logs)


def main(argv: list[str] | None = None) -> int:
    """
    コマンドライン実行時の入口。
    """

    args = parse_args(argv)

    try:
        config = load_config(".env")
        log_dir = args.log_dir or config.log_dir
        delete_logs_before(log_dir, args.delete_before, args.dry_run)
    except Exception as exc:
        print(f"ログ削除に失敗しました: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
