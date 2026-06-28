# Copyright (C) 2026 daigo-friends(tomomori)
# SPDX-License-Identifier: GPL-3.0-only

"""
メール送信モジュール。

SMTPサーバーを使用して、死活監視結果をメール通知します。
このモジュールは「メールを送ることだけ」を担当します。
"""

from __future__ import annotations

import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate

from config import AppConfig


class Mailer:
    """
    SMTPによるメール送信を行うクラス。
    """

    def __init__(self, config: AppConfig) -> None:
        """
        Mailer を初期化する。

        Parameters
        ----------
        config : AppConfig
            SMTPサーバー情報などの設定。
        """

        self.config = config

    def send(self, to_addrs: list[str], subject: str, body: str) -> None:
        """
        メールを送信する。

        Parameters
        ----------
        to_addrs : list[str]
            宛先メールアドレス一覧。
        subject : str
            メール件名。
        body : str
            メール本文。

        Notes
        -----
        宛先が空の場合は、何もせずに戻ります。
        """

        if not to_addrs:
            return

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = self.config.mail_from
        msg["To"] = ", ".join(to_addrs)
        msg["Date"] = formatdate(localtime=True)

        with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=30) as smtp:
            # TLSを使う設定の場合、STARTTLSを実行します。
            if self.config.smtp_use_tls:
                smtp.starttls()

            # SMTP_USER が空の場合は、認証なしSMTPとして扱います。
            if self.config.smtp_user:
                smtp.login(self.config.smtp_user, self.config.smtp_password)

            refused = smtp.send_message(
                msg,
                from_addr=self.config.mail_from,
                to_addrs=to_addrs,
            )
            if refused:
                details = ", ".join(
                    f"{addr}: {code} {message.decode('utf-8', errors='replace') if isinstance(message, bytes) else message}"
                    for addr, (code, message) in refused.items()
                )
                raise RuntimeError(f"一部の宛先がSMTPサーバーに拒否されました: {details}")
