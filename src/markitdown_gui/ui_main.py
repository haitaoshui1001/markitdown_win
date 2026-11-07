"""MarkItDown 图形界面主窗口。"""

from __future__ import annotations

import sys
import threading
import time
import traceback
from importlib.metadata import entry_points
from pathlib import Path

from PyQt5.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QColor, QDesktopServices, QFont
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import settings as cfg
from .engine import (
    CANDIDATE_EXTENSIONS,
    ConvertOptions,
    JobItem,
    collect_sources,
    cu_supported_file_types,
    plan_jobs,
    run_batch,
    validate,
)

STATUS_COLORS = {
    "完成": QColor(0, 128, 0),
    "失败": QColor(200, 0, 0),
    "无内容": QColor(150, 60, 150),
    "跳过": QColor(180, 130, 0),
    "已取消": QColor(120, 120, 120),
    "转换中": QColor(0, 90, 180),
}


class TaskSignals(QObject):
    item_started = pyqtSignal(object)
    item_done = pyqtSignal(object)
    chunk_finished = pyqtSignal()


class BatchTask(QRunnable):
    """一个 QRunnable = 一条线程 = 一批文件 = 一个 MarkItDown 实例。"""

    def __init__(self, items: list[JobItem], opts: ConvertOptions, roots: list[Path], signals: TaskSignals, stop: threading.Event):
        super().__init__()
        self.items = items
        self.opts = opts
        self.roots = roots
        self.signals = signals
        self.stop = stop

    @pyqtSlot()
    def run(self) -> None:
        try:
            run_batch(
                self.items,
                self.opts,
                self.roots,
                on_item=lambda item: self.signals.item_done.emit(item),
                on_start=lambda item: self.signals.item_started.emit(item),
                stop_flag=self.stop.is_set,
            )
        finally:
            self.signals.chunk_finished.emit()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MarkItDown 转 Markdown 工具")
        self.resize(*self._default_size())
        self.setAcceptDrops(True)

        self.opts, self.remember_secret = cfg.load_options()
        self.items: list[JobItem] = []
        self.item_rows: dict[int, int] = {}
        self.folder_roots: list[Path] = []
        self.stop_event = threading.Event()
        self.running = False
        self.active_chunks = 0
        self.done_since_start = 0
        self.total_since_start = 0
        # 快速转换是用户明确挑了保存路径的单发任务，没出文件要弹窗说清楚
        self.announce_item: JobItem | None = None

        self.pool = QThreadPool(self)
        self.signals = TaskSignals()
        self.signals.item_started.connect(self._on_item_started)
        self.signals.item_done.connect(self._on_item_done)
        self.signals.chunk_finished.connect(self._on_chunk_finished)

        self._build_ui()
        self._apply_options_to_widgets()
        self._refresh_statusbar()

    # ------------------------------------------------------------------ UI -- #
    @staticmethod
    def _default_size() -> tuple[int, int]:
        """默认尺寸跟着屏幕走，小屏上不会开出超出工作区的窗口。"""
        avail = QApplication.primaryScreen().availableGeometry()
        w = max(900, min(1340, avail.width() - 60))
        h = max(620, min(860, avail.height() - 60))
        return w, h

    def _build_ui(self) -> None:
        central = QWidget()
        grid = QGridLayout(central)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setVerticalSpacing(6)
        grid.addLayout(self._build_input_bar(), 0, 0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_settings_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([900, 560])
        grid.addWidget(splitter, 1, 0)

        grid.addLayout(self._build_action_bar(), 2, 0)
        # 只有中间那行吃多余高度，否则输入栏和操作栏会被一起撑开
        grid.setRowStretch(1, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("就绪")

    def _build_input_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.btn_add_files = QPushButton("添加文件…")
        self.btn_add_folder = QPushButton("添加文件夹…")
        self.btn_rescan = QPushButton("重新扫描文件夹")
        self.btn_remove = QPushButton("移除选中")
        self.btn_clear = QPushButton("清空队列")
        self.btn_add_files.clicked.connect(self._choose_files)
        self.btn_add_folder.clicked.connect(self._choose_folder)
        self.btn_rescan.clicked.connect(self._rescan_folders)
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear.clicked.connect(self._clear_queue)
        self.lbl_counts = QLabel("队列：0 个文件")
        for b in (self.btn_add_files, self.btn_add_folder, self.btn_rescan, self.btn_remove, self.btn_clear):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.lbl_counts)
        return row

    def _build_left(self) -> QWidget:
        wrap = QWidget()
        vbox = QVBoxLayout(wrap)
        vbox.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["状态", "源文件", "输出文件", "耗时", "说明"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        for col in (1, 2, 4):
            header.setSectionResizeMode(col, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 66)
        self.table.setColumnWidth(3, 66)
        self.table.doubleClicked.connect(self._open_selected_output)
        vbox.addWidget(self.table, 3)

        self.tabs = QTabWidget()
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont("Consolas", 9))
        self.preview.setLineWrapMode(QTextEdit.NoWrap)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)
        self.log.setFont(QFont("Consolas", 9))
        self.tabs.addTab(self.preview, "结果预览")
        self.tabs.addTab(self.log, "运行日志")
        vbox.addWidget(self.tabs, 2)
        return wrap

    def _build_action_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.btn_convert_queue = QPushButton("转换队列（批量）")
        self.btn_quick_one = QPushButton("快速转换单个文件…")
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setEnabled(False)
        self.btn_open_out = QPushButton("打开输出目录")
        self.btn_convert_queue.clicked.connect(self._start_queue)
        self.btn_quick_one.clicked.connect(self._quick_single)
        self.btn_stop.clicked.connect(self.stop_event.set)
        self.btn_open_out.clicked.connect(self._open_output_dir)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.lbl_stats = QLabel("")
        for w in (self.btn_convert_queue, self.btn_quick_one, self.btn_stop):
            row.addWidget(w)
        row.addWidget(self.progress, 2)
        row.addWidget(self.lbl_stats)
        row.addWidget(self.btn_open_out)
        return row

    @staticmethod
    def _group(title: str) -> tuple[QGroupBox, QGridLayout]:
        box = QGroupBox(title)
        lay = QGridLayout(box)
        lay.setColumnStretch(1, 1)
        return box, lay

    @staticmethod
    def _fill_combo(combo: QComboBox, entries: list[tuple[str, str, str]]) -> None:
        """下拉项显示短中文，真实值放 userData，长说明放悬停提示，避免把面板宽度顶爆。"""
        for label, value, tip in entries:
            combo.addItem(label, value)
            combo.setItemData(combo.count() - 1, tip, Qt.ToolTipRole)

    def _build_settings_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(400)
        body = QWidget()
        outer = QVBoxLayout(body)
        outer.setSpacing(8)

        box, g = self._group("输入与扫描")
        self.chk_recurse = QCheckBox("递归子文件夹")
        self.chk_filter_ext = QCheckBox("只收录可识别的扩展名")
        self.chk_hidden = QCheckBox("包含隐藏文件/目录")
        self.spin_workers = QSpinBox()
        self.spin_workers.setRange(1, 16)
        g.addWidget(self.chk_recurse, 0, 0, 1, 2)
        g.addWidget(self.chk_filter_ext, 1, 0, 1, 2)
        g.addWidget(self.chk_hidden, 2, 0, 1, 2)
        g.addWidget(QLabel("并发线程数"), 3, 0)
        g.addWidget(self.spin_workers, 3, 1)
        outer.addWidget(box)

        box, g = self._group("输出")
        self.rb_out_same = QRadioButton("与源文件同目录")
        self.rb_out_dir = QRadioButton("输出到指定目录")
        grp = QButtonGroup(self)
        grp.addButton(self.rb_out_same)
        grp.addButton(self.rb_out_dir)
        self.edit_out_dir = QLineEdit()
        self.edit_out_dir.setPlaceholderText(r"C:\Users\you\Documents\md_out")
        self.edit_out_dir.setEnabled(False)
        self.rb_out_dir.toggled.connect(self.edit_out_dir.setEnabled)
        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self._choose_output_dir)
        g.addWidget(self.rb_out_same, 0, 0, 1, 3)
        g.addWidget(self.rb_out_dir, 1, 0, 1, 3)
        g.addWidget(self.edit_out_dir, 2, 0, 1, 2)
        g.addWidget(btn_browse, 2, 2)
        g.addWidget(QLabel("文件后缀"), 3, 0)
        self.edit_suffix = QLineEdit(".md")
        g.addWidget(self.edit_suffix, 3, 1, 1, 2)
        g.addWidget(QLabel("重名时"), 4, 0)
        self.combo_conflict = QComboBox()
        self._fill_combo(
            self.combo_conflict,
            [
                ("覆盖", "overwrite", "同名输出文件直接重写（与 markitdown 命令行一致）"),
                ("跳过已存在", "skip", "已有输出文件就不再转换"),
                ("加序号", "number", "已有同名文件时写成 sample_1.md"),
            ],
        )
        g.addWidget(self.combo_conflict, 4, 1, 1, 2)
        g.addWidget(QLabel("命名方式"), 5, 0)
        self.combo_naming = QComboBox()
        self._fill_combo(
            self.combo_naming,
            [
                ("自动", "auto", "sample.pdf 和 sample.docx 都想写 sample.md 时，自动改成 sample.pdf.md 以免互相覆盖"),
                ("总是保留原扩展名", "keep_extension", "一律写成 sample.pdf.md 这种形式"),
            ],
        )
        g.addWidget(self.combo_naming, 5, 1, 1, 2)
        outer.addWidget(box)

        box, g = self._group("格式提示（-x / -m / -c）")
        g.addWidget(self._wrap("用于扩展名缺失、内容乱码或识别错误时强制指定类型；一般留空。"), 0, 0, 1, 2)
        self.edit_ext = QLineEdit()
        self.edit_ext.setPlaceholderText(".pdf")
        self.edit_mime = QLineEdit()
        self.edit_mime.setPlaceholderText("application/pdf")
        self.edit_charset = QLineEdit()
        self.edit_charset.setPlaceholderText("UTF-8 / GB18030")
        g.addWidget(QLabel("扩展名"), 1, 0)
        g.addWidget(self.edit_ext, 1, 1)
        g.addWidget(QLabel("MIME 类型"), 2, 0)
        g.addWidget(self.edit_mime, 2, 1)
        g.addWidget(QLabel("字符集"), 3, 0)
        g.addWidget(self.edit_charset, 3, 1)
        g.addWidget(self._wrap("这三项对整批任务生效，混合格式的批量转换请留空，改用「添加文件」后分批转换。"), 4, 0, 1, 2)
        outer.addWidget(box)

        box, g = self._group("转换选项")
        self.chk_keep_uris = QCheckBox("保留 data URI")
        self.chk_keep_uris.setToolTip("--keep-data-uris：默认会截断 base64 内嵌图片，勾选后原样保留")
        self.chk_plugins = QCheckBox("启用第三方插件")
        self.chk_plugins.setToolTip("--use-plugins：加载 pip 安装的 markitdown 插件")
        self.edit_exiftool = QLineEdit()
        self.edit_exiftool.setPlaceholderText("留空则自动在系统路径查找")
        btn_plugins = QPushButton("列出插件")
        btn_plugins.clicked.connect(self._list_plugins)
        g.addWidget(self.chk_keep_uris, 0, 0, 1, 3)
        g.addWidget(self.chk_plugins, 1, 0, 1, 3)
        g.addWidget(QLabel("exiftool 路径"), 2, 0)
        g.addWidget(self.edit_exiftool, 2, 1)
        g.addWidget(btn_plugins, 2, 2)
        outer.addWidget(box)

        box, g = self._group("云端与 LLM（默认全部关闭）")
        self.chk_docintel = QCheckBox("Azure 文档智能")
        self.chk_docintel.setToolTip("-d / --use-docintel：走云端 OCR，需要 Endpoint 和密钥")
        self.edit_di_ep = QLineEdit()
        self.edit_di_ep.setPlaceholderText("https://xxx.cognitiveservices.azure.com/")
        self.edit_di_ver = QLineEdit()
        self.edit_di_ver.setPlaceholderText("API 版本，可留空")
        self.chk_cu = QCheckBox("Azure Content Understanding")
        self.chk_cu.setToolTip("--use-cu：云端理解，需要 --cu-endpoint 和密钥")
        self.edit_cu_ep = QLineEdit()
        self.edit_cu_ep.setPlaceholderText("https://xxx.cu.azure.com")
        self.edit_cu_analyzer = QLineEdit()
        self.edit_cu_analyzer.setPlaceholderText("analyzer ID，留空自动选择")
        self.edit_cu_types = QLineEdit()
        self.edit_cu_types.setPlaceholderText("pdf,docx,pptx；留空表示全部")
        self.chk_llm = QCheckBox("用多模态 LLM 给图片写描述")
        self.edit_llm_base = QLineEdit()
        self.edit_llm_base.setPlaceholderText("Base URL，如 https://api.openai.com/v1")
        self.edit_llm_key = QLineEdit()
        self.edit_llm_key.setEchoMode(QLineEdit.Password)
        self.edit_llm_key.setPlaceholderText("API Key（留空则读环境变量 OPENAI_API_KEY）")
        self.edit_llm_model = QLineEdit()
        self.edit_llm_model.setPlaceholderText("gpt-4o-mini 等")
        self.edit_llm_prompt = QPlainTextEdit()
        self.edit_llm_prompt.setPlaceholderText("Write a detailed caption for this image.")
        self.edit_llm_prompt.setFixedHeight(58)
        self.chk_remember = QCheckBox("把 API Key 明文存进本地配置文件")
        g.addWidget(self.chk_docintel, 0, 0, 1, 2)
        g.addWidget(QLabel("DI Endpoint"), 1, 0)
        g.addWidget(self.edit_di_ep, 1, 1)
        g.addWidget(QLabel("DI API 版本"), 2, 0)
        g.addWidget(self.edit_di_ver, 2, 1)
        g.addWidget(self.chk_cu, 3, 0, 1, 2)
        g.addWidget(QLabel("CU Endpoint"), 4, 0)
        g.addWidget(self.edit_cu_ep, 4, 1)
        g.addWidget(QLabel("CU Analyzer"), 5, 0)
        g.addWidget(self.edit_cu_analyzer, 5, 1)
        g.addWidget(QLabel("CU 文件类型"), 6, 0)
        g.addWidget(self.edit_cu_types, 6, 1)
        g.addWidget(self.chk_llm, 7, 0, 1, 2)
        g.addWidget(QLabel("LLM Base URL"), 8, 0)
        g.addWidget(self.edit_llm_base, 8, 1)
        g.addWidget(QLabel("LLM API Key"), 9, 0)
        g.addWidget(self.edit_llm_key, 9, 1)
        g.addWidget(QLabel("LLM 模型"), 10, 0)
        g.addWidget(self.edit_llm_model, 10, 1)
        g.addWidget(QLabel("LLM 提示词"), 11, 0)
        g.addWidget(self.edit_llm_prompt, 11, 1)
        g.addWidget(self.chk_remember, 12, 0, 1, 2)
        g.addWidget(
            self._wrap("云端转换需要自备密钥：Document Intelligence 读 AZURE_DOCUMENT_INTELLIGENCE_KEY，Content Understanding 读 AZURE_AI_SERVICES_KEY。"),
            13, 0, 1, 2,
        )
        outer.addWidget(box)

        box, g = self._group("配置")
        btn_save = QPushButton("保存")
        btn_export = QPushButton("另存为…")
        btn_import = QPushButton("载入…")
        btn_reset = QPushButton("默认值")
        btn_open_cfg = QPushButton("配置目录")
        btn_save.clicked.connect(self._save_config)
        btn_export.clicked.connect(self._export_config)
        btn_import.clicked.connect(self._import_config)
        btn_reset.clicked.connect(self._reset_config)
        btn_open_cfg.clicked.connect(self._open_config_dir)
        line = QHBoxLayout()
        for b in (btn_save, btn_export, btn_import, btn_reset, btn_open_cfg):
            line.addWidget(b)
        g.addLayout(line, 0, 0, 1, 2)
        # 完整路径只放悬停提示：Windows 路径没有空格，QLabel 换行也撑不开，会把面板顶宽
        self.lbl_cfg = QLabel("退出时自动保存")
        g.addWidget(self.lbl_cfg, 1, 0, 1, 2)
        self._update_cfg_label(cfg.config_path())
        outer.addWidget(box)
        outer.addStretch(1)

        scroll.setWidget(body)
        return scroll

    @staticmethod
    def _wrap(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("color:#555;")
        return label

    # ------------------------------------------------------- option <-> view -- #
    def _collect_options(self) -> ConvertOptions:
        return self.opts.copy(
            extension_hint=self.edit_ext.text(),
            mimetype_hint=self.edit_mime.text(),
            charset_hint=self.edit_charset.text(),
            keep_data_uris=self.chk_keep_uris.isChecked(),
            use_plugins=self.chk_plugins.isChecked(),
            exiftool_path=self.edit_exiftool.text(),
            use_docintel=self.chk_docintel.isChecked(),
            docintel_endpoint=self.edit_di_ep.text(),
            docintel_api_version=self.edit_di_ver.text(),
            use_cu=self.chk_cu.isChecked(),
            cu_endpoint=self.edit_cu_ep.text(),
            cu_analyzer=self.edit_cu_analyzer.text(),
            cu_file_types=self.edit_cu_types.text(),
            llm_enabled=self.chk_llm.isChecked(),
            llm_base_url=self.edit_llm_base.text(),
            llm_api_key=self.edit_llm_key.text(),
            llm_model=self.edit_llm_model.text(),
            llm_prompt=self.edit_llm_prompt.toPlainText(),
            output_mode="folder" if self.rb_out_dir.isChecked() else "alongside",
            output_dir=self.edit_out_dir.text(),
            output_suffix=self.edit_suffix.text(),
            conflict=self.combo_conflict.currentData(),
            name_mode=self.combo_naming.currentData(),
            recurse=self.chk_recurse.isChecked(),
            filter_by_extension=self.chk_filter_ext.isChecked(),
            include_hidden=self.chk_hidden.isChecked(),
            max_workers=self.spin_workers.value(),
        )

    def _apply_options_to_widgets(self) -> None:
        o = self.opts
        self.edit_ext.setText(o.extension_hint)
        self.edit_mime.setText(o.mimetype_hint)
        self.edit_charset.setText(o.charset_hint)
        self.chk_keep_uris.setChecked(o.keep_data_uris)
        self.chk_plugins.setChecked(o.use_plugins)
        self.edit_exiftool.setText(o.exiftool_path)
        self.chk_docintel.setChecked(o.use_docintel)
        self.edit_di_ep.setText(o.docintel_endpoint)
        self.edit_di_ver.setText(o.docintel_api_version)
        self.chk_cu.setChecked(o.use_cu)
        self.edit_cu_ep.setText(o.cu_endpoint)
        self.edit_cu_analyzer.setText(o.cu_analyzer)
        self.edit_cu_types.setText(o.cu_file_types)
        self.chk_llm.setChecked(o.llm_enabled)
        self.edit_llm_base.setText(o.llm_base_url)
        self.edit_llm_key.setText(o.llm_api_key)
        self.edit_llm_model.setText(o.llm_model)
        self.edit_llm_prompt.setPlainText(o.llm_prompt)
        self.chk_remember.setChecked(self.remember_secret)
        self.rb_out_dir.setChecked(o.output_mode == "folder")
        self.rb_out_same.setChecked(o.output_mode != "folder")
        self.edit_suffix.setText(o.output_suffix)
        self.combo_conflict.setCurrentIndex(max(0, self.combo_conflict.findData(o.conflict)))
        self.combo_naming.setCurrentIndex(max(0, self.combo_naming.findData(o.name_mode)))
        self.chk_recurse.setChecked(o.recurse)
        self.chk_filter_ext.setChecked(o.filter_by_extension)
        self.chk_hidden.setChecked(o.include_hidden)
        self.spin_workers.setValue(o.max_workers)

    def _refresh_statusbar(self) -> None:
        try:
            from markitdown.__about__ import __version__ as mv
        except Exception:
            mv = "未安装"
        self.statusBar().showMessage(
            f"markitdown {mv} · Python {sys.version.split()[0]} · 默认可识别 {len(CANDIDATE_EXTENSIONS)} 种扩展名"
            f" · CU 支持类型 {len(cu_supported_file_types())} 种 · 配置 {cfg.config_path()}"
        )

    # ------------------------------------------------------------ 队列操作 -- #
    def _file_filter(self) -> str:
        joined = " ".join(f"*{e}" for e in CANDIDATE_EXTENSIONS)
        return f"可转换文件 ({joined});;所有文件 (*.*)"

    def _choose_files(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(self, "选择要转换的文件", str(Path.home()), self._file_filter())
        if names:
            self.add_sources([Path(n) for n in names])

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择要批量转换的文件夹", str(Path.home()))
        if folder:
            self.add_folder(Path(folder))

    def _rescan_folders(self) -> None:
        folders = list(self.folder_roots)
        for folder in folders:
            self.add_folder(folder)

    def add_folder(self, folder: Path) -> int:
        opts = self._collect_options()
        if folder not in self.folder_roots:
            self.folder_roots.append(folder)
        found = collect_sources([], [folder], opts)
        added = self.add_sources(found, quiet=True)
        self._log(f"扫描 {folder}：命中 {len(found)} 个文件，新增 {added} 个")
        return added

    def add_sources(self, paths: list[Path], quiet: bool = False) -> int:
        existing = {it.source for it in self.items}
        added = 0
        for p in paths:
            rp = p.resolve()
            if rp in existing:
                continue
            existing.add(rp)
            self.items.append(JobItem(source=rp))
            added += 1
        if added:
            self._rebuild_table()
            if not quiet:
                self._log(f"加入队列 {added} 个文件")
        self._update_counts()
        return added

    def _rebuild_table(self) -> None:
        self.table.setRowCount(0)
        self.item_rows = {}
        for item in self.items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col in range(5):
                self.table.setItem(row, col, QTableWidgetItem(""))
            self.item_rows[id(item)] = row
            self._paint_row(item)

    def _paint_row(self, item: JobItem) -> None:
        row = self.item_rows.get(id(item))
        if row is None:
            return
        values = (
            item.status,
            str(item.source),
            str(item.target) if item.target else "",
            f"{item.elapsed:.2f}s" if item.elapsed else "",
            item.message,
        )
        for col, val in enumerate(values):
            self.table.item(row, col).setText(val)
        # 说明列只放短句，完整原因（含 markitdown 原始英文）挂在悬停提示上
        self.table.item(row, 4).setToolTip(item.detail or item.message)
        color = STATUS_COLORS.get(item.status)
        if color is not None:
            for col in (0, 4):
                self.table.item(row, col).setForeground(color)

    def _remove_selected(self) -> None:
        rows = {i.row() for i in self.table.selectedIndexes()}
        if not rows:
            return
        self.items = [it for n, it in enumerate(self.items) if n not in rows]
        self._rebuild_table()
        self._update_counts()

    def _clear_queue(self) -> None:
        if self.running:
            return
        self.items = []
        self.folder_roots = []
        self._rebuild_table()
        self._update_counts()

    def _update_counts(self) -> None:
        self.lbl_counts.setText(f"队列：{len(self.items)} 个文件 · {len(self.folder_roots)} 个文件夹")

    # -------------------------------------------------------------- 转换 -- #
    def _checked_options(self) -> ConvertOptions | None:
        opts = self._collect_options()
        problems = validate(opts)
        if problems:
            QMessageBox.warning(self, "配置有问题", "\n· " + "\n· ".join(problems))
            return None
        return opts

    def _begin_run(self, items: list[JobItem], opts: ConvertOptions, announce: bool = False) -> None:
        self.opts = opts
        self.announce_item = items[0] if announce and len(items) == 1 else None
        self.stop_event.clear()
        self.running = True
        self.total_since_start = len(items)
        self.done_since_start = 0
        self.active_chunks = 0
        self.btn_stop.setEnabled(True)
        self._set_inputs_enabled(False)
        self.progress.setRange(0, len(items))
        self.progress.setValue(0)
        self._refresh_stats()

        chunks = self._partition(items, opts.max_workers)
        self.active_chunks = len(chunks)
        self.pool.setMaxThreadCount(len(chunks))
        for chunk in chunks:
            self.pool.start(BatchTask(chunk, opts, self.folder_roots, self.signals, self.stop_event))

    @staticmethod
    def _partition(items: list[JobItem], n: int) -> list[list[JobItem]]:
        n = max(1, min(n, len(items)))
        return [chunk for chunk in (items[i::n] for i in range(n)) if chunk]

    def _start_queue(self) -> None:
        if self.running:
            return
        opts = self._checked_options()
        if opts is None:
            return
        items = [it for it in self.items if it.status in ("排队中", "失败", "跳过", "已取消", "无内容")]
        if not items:
            if not self.items:
                QMessageBox.information(self, "没有待转换文件", "队列为空，请先「添加文件」或「添加文件夹」。")
                return
            if QMessageBox.question(self, "全部已完成", "队列里的文件都已转换成功，要全部重转一遍吗？") != QMessageBox.Yes:
                return
            items = list(self.items)
        for it in items:
            it.status = "排队中"
            it.message = ""
            it.detail = ""
            it.target = None
            it.elapsed = 0.0
        plan_jobs(items, self.folder_roots, opts)
        self._rebuild_table()
        self._log(f"开始批量转换 {len(items)} 个文件，{opts.max_workers} 线程")
        self._begin_run(items, opts)

    def _quick_single(self) -> None:
        if self.running:
            return
        opts = self._checked_options()
        if opts is None:
            return
        src, _ = QFileDialog.getOpenFileName(self, "选择单个文件", str(Path.home()), self._file_filter())
        if not src:
            return
        source = Path(src).resolve()
        target, _ = QFileDialog.getSaveFileName(
            self,
            "保存为 Markdown",
            str(self._default_single_target(source, opts)),
            "Markdown (*.md);;所有文件 (*.*)",
        )
        if not target:
            return
        item = JobItem(source=source, target=Path(target))
        self.items.append(item)
        self._rebuild_table()
        self._update_counts()
        self._log(f"快速转换 {source.name} → {target}")
        self._begin_run([item], opts.copy(conflict="overwrite"), announce=True)

    def _default_single_target(self, source: Path, opts: ConvertOptions) -> Path:
        suffix = opts.output_suffix.strip() or ".md"
        if opts.output_mode == "folder" and opts.output_dir.strip():
            return Path(opts.output_dir).expanduser() / f"{source.stem}{suffix}"
        return source.with_name(f"{source.stem}{suffix}")

    @pyqtSlot(object)
    def _on_item_started(self, item: JobItem) -> None:
        # 只重画，不改 item.status——状态归工作线程管，否则快速批量会互相覆盖
        self._paint_row(item)

    @pyqtSlot(object)
    def _on_item_done(self, item: JobItem) -> None:
        self.done_since_start += 1
        self.progress.setValue(self.done_since_start)
        self._paint_row(item)
        self._refresh_stats()
        if item.status in ("失败", "无内容"):
            self._log(f"{item.status} {item.source.name}：{item.message}")
            if item.detail and item.detail != item.message:
                self._log("  " + item.detail)

    def _refresh_stats(self) -> None:
        done = sum(1 for it in self.items if it.status == "完成")
        fail = sum(1 for it in self.items if it.status == "失败")
        empty = sum(1 for it in self.items if it.status == "无内容")
        left = max(self.total_since_start - self.done_since_start, 0)
        extra = f" · 无内容 {empty}" if empty else ""
        self.lbl_stats.setText(f"本轮完成 {done} · 失败 {fail}{extra} · 剩余 {left}")

    @pyqtSlot()
    def _on_chunk_finished(self) -> None:
        self.active_chunks -= 1
        if self.active_chunks > 0:
            return
        self.running = False
        self.btn_stop.setEnabled(False)
        self._set_inputs_enabled(True)
        total = sum(it.chars for it in self.items)
        self._log(f"本轮结束，累计输出 {total} 字符")
        empty = [it for it in self.items if it.status == "无内容"]
        if empty:
            names = "、".join(it.source.name for it in empty[:5]) + ("…" if len(empty) > 5 else "")
            self._log(f"{len(empty)} 个文件没有可提取的正文，未生成 Markdown：{names}")
            self._log("  图片需要 OCR 或多模态描述、音频需要语音转写；离线状态下这些内容无法变成文字。")
        self._announce_quick_single()

    def _announce_quick_single(self) -> None:
        """快速转换没产出文件时直接告诉用户，而不是让他去找那个不存在的 md。"""
        item, self.announce_item = self.announce_item, None
        if item is None or item.status in ("完成", "已取消"):
            return
        if item.status == "跳过":
            QMessageBox.information(self, "未覆盖已有文件", f"{item.source.name}\n\n输出文件已存在，按当前重名策略跳过了。")
            return
        body = f"{item.source.name}\n\n{item.message}"
        if item.detail and item.detail != item.message:
            body += "\n\n" + item.detail
        QMessageBox.warning(self, "未能生成 Markdown", body)

    def _set_inputs_enabled(self, enabled: bool) -> None:
        for b in (
            self.btn_add_files,
            self.btn_add_folder,
            self.btn_rescan,
            self.btn_remove,
            self.btn_clear,
            self.btn_convert_queue,
            self.btn_quick_one,
        ):
            b.setEnabled(enabled)

    # --------------------------------------------------------- 辅助动作 -- #
    def _choose_output_dir(self) -> None:
        start = self.edit_out_dir.text() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录", start)
        if folder:
            self.edit_out_dir.setText(folder)
            self.rb_out_dir.setChecked(True)

    def _update_cfg_label(self, path: Path) -> None:
        self.lbl_cfg.setToolTip(f"配置文件：{path}")

    def _open_config_dir(self) -> None:
        cfg.config_dir().mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(cfg.config_dir())))

    def _list_plugins(self) -> None:
        eps = list(entry_points(group="markitdown.plugin"))
        if not eps:
            QMessageBox.information(self, "插件", "当前没有安装 MarkItDown 第三方插件。")
            return
        QMessageBox.information(self, "已安装插件", "\n".join(f"· {e.name}\t{e.value}" for e in eps))

    def _open_selected_output(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows or rows[0] >= len(self.items):
            return
        item = self.items[rows[0]]
        if item.target and item.target.exists():
            self._show_preview(item.target)
        else:
            self._log(f"{item.source.name} 暂无输出文件（状态：{item.status}）")

    def _show_preview(self, path: Path) -> None:
        try:
            self.preview.setPlainText(path.read_text(encoding="utf-8", errors="replace")[:200_000])
        except OSError as exc:
            self._log(f"读取预览失败：{exc}")
            return
        self.tabs.setCurrentWidget(self.preview)

    def _open_output_dir(self) -> None:
        opts = self._collect_options()
        target: Path | None = None
        for it in reversed(self.items):
            if it.target:
                target = it.target.parent
                break
        if target is None and opts.output_dir.strip():
            target = Path(opts.output_dir).expanduser()
        if target is None:
            target = Path.home()
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _save_config(self) -> None:
        self.opts = self._collect_options()
        self.remember_secret = self.chk_remember.isChecked()
        path = cfg.save_options(self.opts, self.remember_secret)
        self._update_cfg_label(path)
        self._log(f"配置已保存到 {path}")
        self._refresh_statusbar()

    def _export_config(self) -> None:
        target, _ = QFileDialog.getSaveFileName(self, "导出配置", str(cfg.config_path()), "JSON (*.json)")
        if target:
            cfg.write_options_to(Path(target), self._collect_options(), self.chk_remember.isChecked())
            self._log(f"配置已导出到 {target}")

    def _import_config(self) -> None:
        start, _ = QFileDialog.getOpenFileName(self, "载入配置", str(cfg.config_dir()), "JSON (*.json)")
        if not start:
            return
        try:
            self.opts, self.remember_secret = cfg.read_options_from(Path(start))
        except Exception as exc:
            QMessageBox.critical(self, "载入失败", str(exc))
            return
        self._apply_options_to_widgets()
        self._log(f"已载入配置 {start}")

    def _reset_config(self) -> None:
        if QMessageBox.question(self, "恢复默认", "确定把所有参数恢复为默认值？") != QMessageBox.Yes:
            return
        self.opts = ConvertOptions()
        self.remember_secret = False
        self._apply_options_to_widgets()

    def _log(self, message: str) -> None:
        self.log.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {message}")

    # ------------------------------------------------------------ 拖拽 -- #
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        files: list[Path] = []
        for url in event.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_dir():
                self.add_folder(p)
            elif p.is_file():
                files.append(p)
        if files:
            self.add_sources(files)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.stop_event.set()
        if self.running:
            self.pool.waitForDone(5000)
        try:
            cfg.save_options(self._collect_options(), self.chk_remember.isChecked())
        except Exception:
            self._log("保存配置失败：\n" + traceback.format_exc())
        event.accept()


def main() -> int:
    # 必须在 QApplication 创建前设置，否则 150%/200% 缩放的屏幕上整界面会偏小
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    # 默认策略会把 150% 进位成 200%，界面整体过大；PassThrough 按真实比例缩放
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("MarkItDown GUI")
    window = MainWindow()
    window.show()
    return app.exec_()
