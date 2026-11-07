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
from markitdown_gui.engine import ConvertOptions, JobItem, validate  # noqa: E402
from markitdown_gui.ui_main import STATUS_COLORS, MainWindow  # noqa: E402


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

    # 「无内容」是新增状态：要能上色、能把完整原因挂在悬停提示上、统计行单独计数
    empty_item = JobItem(
        source=ROOT / "samples" / "sample.pdf",
        status="无内容",
        message="图片无文字层，离线提不到正文",
        detail="markitdown 不含 OCR：图片只能取 exiftool 元数据或多模态描述。",
    )
    win.items.append(empty_item)
    win._rebuild_table()
    row = win.item_rows[id(empty_item)]
    assert win.table.item(row, 0).text() == "无内容", win.table.item(row, 0).text()
    assert win.table.item(row, 0).foreground().color() == STATUS_COLORS["无内容"], "无内容状态未着色"
    assert win.table.item(row, 4).toolTip().startswith("markitdown 不含 OCR"), win.table.item(row, 4).toolTip()
    assert win.table.item(row, 4).foreground().color() == STATUS_COLORS["无内容"], "说明列未跟随着色"
    win._refresh_stats()
    assert "无内容 1" in win.lbl_stats.text(), win.lbl_stats.text()
    print("无内容渲染:", win.lbl_stats.text())

    # 回归：started 信号不能改写状态，否则快速批量会把「完成」覆盖成「转换中」
    race_item = JobItem(source=ROOT / "samples" / "sample.pdf", status="完成", chars=12)
    win.items.append(race_item)
    win._rebuild_table()
    win._on_item_started(race_item)
    assert race_item.status == "完成", f"started 回调覆盖了状态：{race_item.status}"
    row = win.item_rows[id(race_item)]
    assert win.table.item(row, 0).text() == "完成", win.table.item(row, 0).text()
    print("started 覆盖回归: OK")

    win._remove_selected()
    win._clear_queue()
    assert win.table.rowCount() == 0 and not win.items
    QTimer.singleShot(50, app.quit)
    app.exec_()
    print("UI_SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
