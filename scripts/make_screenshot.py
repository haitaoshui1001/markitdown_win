"""生成 README 的两张界面截图，都是真实转换后的结果。

    .venv\\Scripts\\python.exe scripts/make_screenshot.py

产出 assets/screenshot.png（全部成功）与 assets/screenshot-no-content.png（含无内容/失败行）。
转换出来的 .md 会在抓图后删掉，临时媒体文件放在系统临时目录。
"""

from __future__ import annotations

import struct
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image  # noqa: E402
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


def make_media() -> list[Path]:
    """造几个离线转不出正文的文件：png/jpg（无 OCR）、gif（不支持）、wav（需转写）。"""
    media = Path(tempfile.mkdtemp(prefix="mkd-shot-media-"))
    solid = Image.new("RGB", (80, 60), (200, 40, 40))
    solid.save(media / "photo.png")
    solid.save(media / "pic.jpg")
    solid.save(media / "icon.gif")
    with wave.open(str(media / "voice.wav"), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(struct.pack("<" + "h" * 400, *([500] * 400)))
    return sorted(media.iterdir())


def capture(app: QApplication, sources: list[Path], dst: Path, opts: ConvertOptions) -> dict[str, str]:
    win = ui_main.MainWindow()
    win.resize(*WIN_SIZE)
    win.show()
    app.processEvents()

    items = [JobItem(source=p) for p in sources]
    win.items.extend(items)
    plan_jobs(items, win.folder_roots, opts)
    win._rebuild_table()
    app.processEvents()

    started = time.monotonic()
    run_batch(items, opts, win.folder_roots)
    for it in items:
        win._paint_row(it)
    win._update_counts()
    win._refresh_stats()

    done = [it for it in items if it.status == "完成"]
    if done:
        pick = next((it for it in done if it.source.name == PREVIEW_OF), done[0])
        win.table.setCurrentCell(win.item_rows[id(pick)], 0)
        win._show_preview(pick.target)
    win.statusBar().showMessage("")
    for _ in range(3):
        app.processEvents()

    pixmap = win.grab()
    pixmap.save(str(dst))
    print(f"{dst.name}: {pixmap.width()}x{pixmap.height()} 用时 {time.monotonic() - started:.1f}s")

    statuses = {it.source.name: it.status for it in items}
    for it in items:
        if it.target and it.target.exists():
            it.target.unlink()
    win.close()
    return statuses


def main() -> int:
    app = QApplication(sys.argv)
    opts = ConvertOptions()
    samples = sorted((ROOT / "samples").resolve().iterdir())

    statuses = capture(app, samples, ROOT / "assets" / "screenshot.png", opts)
    print("  全部完成" if set(statuses.values()) == {"完成"} else f"  意外状态：{statuses}")

    media = make_media()
    statuses = capture(app, samples + media, ROOT / "assets" / "screenshot-no-content.png", opts)
    print("  " + " · ".join(f"{name}:{status}" for name, status in statuses.items() if status != "完成"))
    for p in media:
        p.unlink()
    media[0].parent.rmdir()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
