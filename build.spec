# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：产出 dist/MarkItDownGUI/MarkItDownGUI.exe（目录版）。

用法：
    .venv\\Scripts\\pyinstaller.exe build.spec --noconfirm
"""

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = []
hiddenimports = []

# magika 运行时要在包目录里找 onnx 模型和配置文件，漏掉会直接「初始化失败」
datas += collect_data_files("magika")

# 这些包在 markitdown 里是 try/except 惰性导入，静态分析容易漏
optional_packages = [
    "azure.ai.documentintelligence",
    "azure.ai.contentunderstanding",
    "openai",
    "youtube_transcript_api",
    "PIL",
    "soundfile",
    "pydub",
    "olefile",
    "pbixray",
]
for pkg in optional_packages:
    try:
        __import__(pkg)
    except ImportError:
        continue
    hiddenimports.append(pkg)

for pkg in ("markitdown",):
    hiddenimports += collect_submodules(pkg)

# 只用到 QtWidgets/QtGui/QtCore，其余 Qt 模块和 tkinter 全部剔掉以缩小体积
excludes = [
    "tkinter",
    "PyQt5.QtWebEngineWidgets",
    "PyQt5.QtWebEngineCore",
    "PyQt5.QtQml",
    "PyQt5.QtQuick",
    "PyQt5.QtQuickWidgets",
    "PyQt5.QtCharts",
    "PyQt5.QtDataVisualization",
    "PyQt5.Qt3DCore",
    "PyQt5.QtMultimedia",
    "PyQt5.QtNetwork",
    "PyQt5.QtBluetooth",
    "PyQt5.QtPositioning",
    "PyQt5.QtSensors",
    "PyQt5.QtSerialPort",
    "PyQt5.QtTextToSpeech",
    "PyQt5.QtRemoteObjects",
    "PyQt5.QtScxml",
    "PyQt5.QtSvg",
    "PyQt5.QtTest",
    "PyQt5.QtPdf",
    "PyQt5.QtVirtualKeyboard",
    "PyQt5.QtWinExtras",
    "matplotlib",
    "scipy",
    "IPython",
    "notebook",
    "pytest",
]

icon_file = os.path.join(SPECPATH, "assets", "app.ico")
if not os.path.exists(icon_file):
    icon_file = None

a = Analysis(
    [os.path.join(SPECPATH, "app_entry.py")],
    pathex=[os.path.join(SPECPATH, "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MarkItDownGUI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MarkItDownGUI",
)
