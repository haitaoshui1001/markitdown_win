"""程序入口。

    python -m markitdown_gui                启动图形界面
    python -m markitdown_gui --selftest A B 无界面转换并退出（用于验证打包产物）
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path


def _selftest(argv: list[str]) -> int:
    """无界面转换，供打包后验证使用。windowed exe 没有 stdout，结果写进日志文件。"""
    from .engine import ConvertOptions, convert_one, new_markitdown

    if len(argv) < 2:
        return 2
    src, dst = Path(argv[0]), Path(argv[1])
    opts = ConvertOptions()
    if len(argv) > 2:
        opts = ConvertOptions.from_dict(json.loads(Path(argv[2]).read_text(encoding="utf-8")))

    dst.parent.mkdir(parents=True, exist_ok=True)
    log = dst.with_name(dst.name + ".selftest.log")
    try:
        text = convert_one(new_markitdown(opts), src, opts)
        dst.write_text(text, encoding="utf-8")
    except Exception as exc:
        log.write_text(f"SELFTEST_FAIL {type(exc).__name__}: {exc}\n\n{traceback.format_exc()}", encoding="utf-8")
        return 1
    log.write_text(f"SELFTEST_OK chars={len(text)} out={dst}", encoding="utf-8")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if "--selftest" in argv:
        return _selftest([a for a in argv if a != "--selftest"])
    from .ui_main import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
