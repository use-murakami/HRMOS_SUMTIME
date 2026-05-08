"""
ログ設定モジュール

Cloud Functions では標準出力への出力が自動的に Cloud Logging に取り込まれる。
"""
import logging
import sys


def get_logger(name: str) -> logging.Logger:
    """
    ロガーを取得する。

    Args:
        name: ロガー名（通常は __name__ を使用）

    Returns:
        設定済みロガー
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    return logger
