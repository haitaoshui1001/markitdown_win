"""生成 README 用的界面截图：真把 samples/ 转一遍，画进表格后 grab。

    .venv\\Scripts\\python.exe scripts/make_screenshot.py

产物 assets/screenshot.png。转换出来的 .md 会在保存截图后删掉。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

from markitdown_gui import ui_main  # noqa: E402
from markitdown_gui.engine import ConvertOptions, JobItem, plan_jobs, run_batch  # noqa: E402

# 宽到能让源文件/输出文件两列的路径不省略，又不超过常见屏幕工作区
WIN_SIZE = (1680, 940)
PREVIEW_OF = "sample.html"


def main() -> int:
    app = QApplication(sys.argv)
    win = ui_main.MainWindow()
    win.resize(*WIN_SIZE)
    win.show()
    app.processEvents()

    items = [JobItem(source=p) for p in sorted((ROOT / "samples").resolve().iterdir())]
    win.items.extend(items)
    opts = ConvertOptions()
    plan_jobs(items, win.folder_roots, opts)
    win._rebuild_table()
    app.processEvents()

    started = time.monotonic()
    run_batch(items, opts, win.folder_roots)
    for it in items:
        win._paint_row(it)
    win._update_counts()

    done = [it for it in items if it.status == "完成"]
    print(f"转换 {len(done)}/{len(items)} 成功，用时 {time.monotonic() - started:.1f}s")
    for it in items:
        print(f"  {it.source.name}: {it.status} {it.chars} 字符 {it.message}")

    pick = next((it for it in done if it.source.name == PREVIEW_OF), done[0])
    win.table.setCurrentCell(win.item_rows[id(pick)], 0)
    win._show_preview(pick.target)
    win.statusBar().showMessage(f"本轮完成 {len(done)} · 失败 {len(items) - len(done)}")
    for _ in range(3):
        app.processEvents()

    pixmap = win.grab()
    dst = ROOT / "assets" / "screenshot.png"
    pixmap.save(str(dst))
    print(f"已保存 {dst} {pixmap.width()}x{pixmap.height()}")

    for it in items:
        if it.target and it.target.exists():
            it.target.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
