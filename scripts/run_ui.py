"""启动智能问数 Streamlit 前端（服务器上运行）。

用法：
  python scripts/run_ui.py                 # 默认 streamlit run src/ui/app.py
  python scripts/run_ui.py --port 8502     # 指定端口
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "src", "ui", "app.py")


def main():
    parser = argparse.ArgumentParser(description="智能问数 Streamlit 前端")
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()
    cmd = [sys.executable, "-m", "streamlit", "run", APP,
           "--server.port", str(args.port), "--server.headless", "true"]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
