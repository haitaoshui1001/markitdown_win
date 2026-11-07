"""PyInstaller 入口：开发态直接跑，打包后由 build.spec 使用。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from markitdown_gui.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
