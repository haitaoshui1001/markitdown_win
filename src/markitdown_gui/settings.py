"""界面配置的持久化：默认存在 %APPDATA%\\MarkItDownGUI\\config.json。

API Key 只有勾选「记住密钥」后才落盘，否则每次从环境变量 OPENAI_API_KEY 读取。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .engine import ConvertOptions

SECRET_FIELDS = ("llm_api_key",)


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("HOME") or str(Path.home())
    return Path(base) / "MarkItDownGUI"


def config_path() -> Path:
    return config_dir() / "config.json"


def load_options() -> tuple[ConvertOptions, bool]:
    """返回 (配置, 是否记住密钥)。文件缺失或损坏时用默认值。"""
    remember = False
    data: dict = {}
    try:
        raw = json.loads(config_path().read_text(encoding="utf-8"))
        remember = bool(raw.get("_remember_secret", False))
        data = {k: v for k, v in raw.items() if not k.startswith("_")}
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, OSError):
        pass
    opts = ConvertOptions.from_dict(data)
    if not remember:
        opts.llm_api_key = ""
    if not opts.llm_api_key:
        opts.llm_api_key = os.environ.get("OPENAI_API_KEY", "")
    return opts, remember


def save_options(opts: ConvertOptions, remember_secret: bool) -> Path:
    data = opts.to_dict()
    data["_remember_secret"] = bool(remember_secret)
    if not remember_secret:
        data[SECRET_FIELDS[0]] = ""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_options_to(path: Path, opts: ConvertOptions, remember_secret: bool) -> None:
    data = opts.to_dict()
    data["_remember_secret"] = bool(remember_secret)
    if not remember_secret:
        data[SECRET_FIELDS[0]] = ""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_options_from(path: Path) -> tuple[ConvertOptions, bool]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    remember = bool(raw.get("_remember_secret", False))
    opts = ConvertOptions.from_dict({k: v for k, v in raw.items() if not k.startswith("_")})
    return opts, remember


def app_dir() -> Path:
    """打包后是 exe 所在目录，开发时是项目根。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]
