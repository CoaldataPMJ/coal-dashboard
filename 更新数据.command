#!/bin/bash
set -euo pipefail
COAL_SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
COAL_DATA_LOCATION="${1:-$HOME/Desktop/周报日报数据库}"
if ! command -v python3 >/dev/null 2>&1; then
  echo '需要 Python 3.9 或更新版本。'
  exit 1
fi
if ! python3 -c 'import openpyxl' >/dev/null 2>&1; then
  echo "请先运行：python3 -m pip install -r \"$COAL_SCRIPT_DIR/requirements.txt\""
  exit 1
fi
if [ -f "$COAL_DATA_LOCATION" ]; then
  python3 "$COAL_SCRIPT_DIR/extract_dashboard_data.py" --source "$COAL_DATA_LOCATION" --output-dir "$COAL_SCRIPT_DIR"
elif [ -d "$COAL_DATA_LOCATION" ]; then
  cd -- "$COAL_DATA_LOCATION"
  python3 "$COAL_SCRIPT_DIR/extract_dashboard_data.py" --output-dir "$COAL_SCRIPT_DIR"
else
  echo '未找到数据库位置。请在脚本后传入 Excel 文件或所在文件夹路径。'
  exit 1
fi
echo '本地 data.js 已更新。将此文件提交到 GitHub 仓库即可更新网页。'
