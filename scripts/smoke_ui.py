"""离屏冒烟测试：不真正转换，只验证界面能否构建、队列/校验/配置读写是否正常。

    python scripts/smoke_ui.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="mkd-smoke-")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PyQt5.QtCore import QTimer  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from markitdown_gui import settings as cfg  # noqa: E402
from markitdown_gui.engine import ConvertOptions, validate  # noqa: E402
from markitdown_gui.ui_main import MainWindow  # noqa: E402


def main() -> int:
    app = QApplication([])
    win = MainWindow()
    win.show()

    win.add_sources([ROOT / "app_entry.py", ROOT / "build.spec", ROOT / "app_entry.py"])
    assert len(win.items) == 2, f"重复添加应被去重，实际 {len(win.items)}"
    win.add_folder(ROOT / "src")
    assert win.table.rowCount() == len(win.items) == 2 + 5, f"队列/表格行数不一致 {win.table.rowCount()} vs {len(win.items)}"

    opts = win._collect_options()
    assert opts.max_workers == 2 and opts.conflict == "overwrite" and opts.output_mode == "alongside"
    assert validate(opts) == [], validate(opts)

    win.chk_docintel.setChecked(True)
    win.chk_cu.setChecked(True)
    win.chk_llm.setChecked(True)
    problems = validate(win._collect_options())
    assert any("Endpoint" in p for p in problems), problems
    assert any("互斥" in p for p in problems), problems
    assert any("模型名" in p for p in problems), problems
    print("校验拦截:", " | ".join(problems))

    win.chk_docintel.setChecked(False)
    win.chk_cu.setChecked(False)
    win.chk_llm.setChecked(False)
    saved = cfg.save_options(ConvertOptions(output_mode="folder", output_dir="D:/out", conflict="number"), False)
    reloaded, remember = cfg.load_options()
    assert reloaded.conflict == "number" and reloaded.output_dir == "D:/out", reloaded
    assert remember is False and reloaded.llm_api_key == ""
    print("配置读写:", saved)

    win._remove_selected()
    win._clear_queue()
    assert win.table.rowCount() == 0 and not win.items
    QTimer.singleShot(50, app.quit)
    app.exec_()
    print("UI_SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
