"""
pytest 設定ファイル

cloud_functions/ ディレクトリをモジュール検索パスに追加する。
tests/ 内から `import config` や `from utils.xxx import ...` が使えるようになる。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
