"""MiniQbot-Lite Web Console 启动器

运行: venv/bin/python web/run.py
访问: http://127.0.0.1:8000
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web"))

import uvicorn

if __name__ == "__main__":
    print("\n🚀 MiniQbot-Lite Web Console")
    print("   → http://127.0.0.1:8000")
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
