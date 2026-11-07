"""markitdown 转换引擎：纯 Python，不依赖任何 UI，便于单独测试与复用。"""

from __future__ import annotations

import codecs
import os
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable

# 批量扫描时默认可识别的扩展名；勾选「不按扩展名过滤」后忽略此表。
# 注意：markitdown 离线不支持老版 .doc/.ppt/.rtf，故未列入。
CANDIDATE_EXTENSIONS: tuple[str, ...] = (
    ".pdf", ".docx", ".xlsx", ".xls", ".pptx", ".ppsx", ".sldx", ".thmx", ".msg",
    ".html", ".htm", ".xml", ".csv", ".json", ".txt", ".md", ".markdown",
    ".log", ".ini", ".conf", ".yaml", ".yml", ".tex", ".bib",
    ".epub", ".ipynb", ".zip", ".py", ".js", ".ts", ".css", ".sql",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp",
    ".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac",
)


@dataclass
class ConvertOptions:
    # ---- 格式提示（对应 -x / -m / -c）----
    extension_hint: str = ""
    mimetype_hint: str = ""
    charset_hint: str = ""
    # ---- 转换行为（对应 --keep-data-uris / -p）----
    keep_data_uris: bool = False
    use_plugins: bool = False
    exiftool_path: str = ""
    # ---- Azure Document Intelligence（对应 -d / -e）----
    use_docintel: bool = False
    docintel_endpoint: str = ""
    docintel_api_version: str = ""
    # ---- Azure Content Understanding（对应 --use-cu 系列）----
    use_cu: bool = False
    cu_endpoint: str = ""
    cu_analyzer: str = ""
    cu_file_types: str = ""
    # ---- 多模态 LLM 图片描述（Python API 独有）----
    llm_enabled: bool = False
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_prompt: str = ""
    # ---- 输入/输出编排 ----
    output_mode: str = "alongside"  # alongside | folder
    output_dir: str = ""
    output_suffix: str = ".md"
    conflict: str = "overwrite"  # overwrite | skip | number
    name_mode: str = "auto"  # auto（重名才保留原扩展名）| keep_extension（总是保留）
    recurse: bool = True
    filter_by_extension: bool = True
    include_hidden: bool = False
    max_workers: int = 2

    def copy(self, **changes: Any) -> "ConvertOptions":
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConvertOptions":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class JobItem:
    source: Path
    target: Path | None = None
    status: str = "排队中"
    message: str = ""
    elapsed: float = 0.0
    chars: int = 0


class ConversionError(Exception):
    """配置或转换过程中可直接展示给用户的错误。"""


# --------------------------------------------------------------------------- #
# 配置校验与 markitdown 对象构造
# --------------------------------------------------------------------------- #
def validate(opts: ConvertOptions) -> list[str]:
    problems: list[str] = []
    if opts.use_docintel and not opts.docintel_endpoint.strip():
        problems.append("启用了文档智能，但未填写 Endpoint（同时需要 AZURE_DOCUMENT_INTELLIGENCE_KEY 环境变量或凭据）。")
    if opts.use_docintel and opts.use_cu:
        problems.append("文档智能与 Content Understanding 互斥，只能启用其中一个。")
    if opts.use_cu:
        if not opts.cu_endpoint.strip():
            problems.append("启用了 Content Understanding，但未填写 --cu-endpoint。")
        for name in _cu_type_names(opts.cu_file_types):
            if name not in cu_supported_file_types():
                problems.append(f"Content Understanding 不支持文件类型「{name}」。")
    if opts.llm_enabled and not opts.llm_model.strip():
        problems.append("启用了图片 LLM 描述，但未填写模型名。")
    if opts.llm_enabled and not _api_key(opts):
        problems.append("启用了图片 LLM 描述，但没有 API Key（界面里填，或设置环境变量 OPENAI_API_KEY）。")
    if opts.extension_hint.strip():
        if not _clean_ext(opts.extension_hint):
            problems.append(f"扩展名提示「{opts.extension_hint}」不合法。")
    if opts.mimetype_hint.strip() and opts.mimetype_hint.count("/") != 1:
        problems.append(f"MIME 类型「{opts.mimetype_hint}」不合法，应形如 application/pdf。")
    if opts.charset_hint.strip():
        try:
            codecs.lookup(opts.charset_hint.strip())
        except LookupError:
            problems.append(f"字符集「{opts.charset_hint}」不被识别，例如可用 UTF-8、GB18030。")
    if opts.output_mode == "folder" and not opts.output_dir.strip():
        problems.append("输出到指定目录，但目录为空。")
    if opts.output_suffix.strip() and not opts.output_suffix.strip().startswith("."):
        problems.append("输出后缀应以 . 开头，例如 .md")
    return problems


def _clean_ext(value: str) -> str | None:
    v = (value or "").strip().lower()
    if not v:
        return None
    return v if v.startswith(".") else "." + v


def _api_key(opts: ConvertOptions) -> str:
    return opts.llm_api_key.strip() or os.environ.get("OPENAI_API_KEY", "").strip()


def _cu_type_names(raw: str) -> list[str]:
    return [t.strip().lower() for t in (raw or "").split(",") if t.strip()]


def cu_supported_file_types() -> list[str]:
    try:
        from markitdown.converters import ContentUnderstandingFileType
    except Exception:
        return []
    return sorted(str(v.value).lower() for v in ContentUnderstandingFileType)


def build_kwargs(opts: ConvertOptions) -> dict[str, Any]:
    """把界面配置翻译成 MarkItDown(...) 的关键字参数。"""
    kwargs: dict[str, Any] = {"enable_plugins": bool(opts.use_plugins)}

    if opts.use_docintel:
        kwargs["docintel_endpoint"] = opts.docintel_endpoint.strip()
        if opts.docintel_api_version.strip():
            kwargs["docintel_api_version"] = opts.docintel_api_version.strip()

    if opts.use_cu:
        kwargs["cu_endpoint"] = opts.cu_endpoint.strip()
        if opts.cu_analyzer.strip():
            kwargs["cu_analyzer_id"] = opts.cu_analyzer.strip()
        names = _cu_type_names(opts.cu_file_types)
        if names:
            from markitdown.converters import ContentUnderstandingFileType

            kwargs["cu_file_types"] = [ContentUnderstandingFileType(n) for n in names]

    if opts.llm_enabled:
        kwargs["llm_client"] = _build_llm_client(opts)
        kwargs["llm_model"] = opts.llm_model.strip()
        if opts.llm_prompt.strip():
            kwargs["llm_prompt"] = opts.llm_prompt.strip()

    if opts.exiftool_path.strip():
        kwargs["exiftool_path"] = opts.exiftool_path.strip()

    return kwargs


def _build_llm_client(opts: ConvertOptions):
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise ConversionError("未安装 openai 包，无法启用图片 LLM 描述。") from exc
    kwargs: dict[str, Any] = {"api_key": _api_key(opts)}
    if opts.llm_base_url.strip():
        kwargs["base_url"] = opts.llm_base_url.strip()
    return OpenAI(**kwargs)


def new_markitdown(opts: ConvertOptions):
    from markitdown import MarkItDown

    return MarkItDown(**build_kwargs(opts))


def new_stream_info(opts: ConvertOptions):
    from markitdown import StreamInfo

    ext = _clean_ext(opts.extension_hint)
    mime = (opts.mimetype_hint or "").strip() or None
    charset = (opts.charset_hint or "").strip() or None
    if ext is None and mime is None and charset is None:
        return None
    return StreamInfo(extension=ext, mimetype=mime, charset=charset)


# --------------------------------------------------------------------------- #
# 文件枚举与输出路径编排
# --------------------------------------------------------------------------- #
def collect_sources(files: Iterable[Path], folders: Iterable[Path], opts: ConvertOptions) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()

    suffix = opts.output_suffix.strip().lower() or ".md"
    out_root = (
        Path(opts.output_dir).expanduser().resolve()
        if opts.output_mode == "folder" and opts.output_dir.strip()
        else None
    )
    folder_roots = [f.resolve() for f in folders if f.is_dir()]

    def keep(path: Path) -> bool:
        if not path.is_file():
            return False
        if not opts.include_hidden and any(part.startswith(".") for part in path.parts):
            return False
        lowered = path.suffix.lower()
        if opts.filter_by_extension and lowered not in CANDIDATE_EXTENSIONS:
            return False
        # 不要把自己上一轮生成的 .md 再转一遍
        if lowered == suffix and (_inside(path, out_root) or any(_inside(path, r) for r in folder_roots)):
            return False
        rp = path.resolve()
        if rp in seen:
            return False
        seen.add(rp)
        return True

    for f in files:
        if keep(f):
            found.append(f)

    for folder in folder_roots:
        candidates = folder.rglob("*") if opts.recurse else folder.glob("*")
        for candidate in sorted(candidates, key=lambda p: str(p).lower()):
            if keep(candidate):
                found.append(candidate)
    return found


def _inside(path: Path, root: Path | None) -> bool:
    if root is None:
        return False
    try:
        path.resolve().relative_to(root)
    except (ValueError, OSError):
        return False
    return True


def target_for(source: Path, roots: Iterable[Path], opts: ConvertOptions, keep_extension: bool) -> Path:
    """算出某个源文件的输出路径。keep_extension=True 时用 sample.pdf.md 这种命名。"""
    suffix = opts.output_suffix.strip() or ".md"
    stem = source.stem + (source.suffix if keep_extension else "")
    if opts.output_mode == "folder" and opts.output_dir.strip():
        rel_dir = Path(".")
        for root in roots:
            try:
                rel_dir = source.resolve().relative_to(root.resolve()).parent
                break
            except (ValueError, OSError):
                continue
        return Path(opts.output_dir).expanduser() / rel_dir / (stem + suffix)
    return source.with_name(stem + suffix)


def _numbered(path: Path, n: int) -> Path:
    return path.with_name(f"{path.stem}_{n}{path.suffix}")


def unique_path(path: Path) -> Path:
    candidate = path
    n = 1
    while candidate.exists():
        candidate = _numbered(path, n)
        n += 1
    return candidate


def plan_jobs(items: list[JobItem], roots: Iterable[Path], opts: ConvertOptions) -> None:
    """转换前单线程分配好所有输出路径。

    不同格式常有同一个主名（sample.pdf / sample.docx），直接写 sample.md 会互相覆盖，
    所以重名时改用保留原扩展名的命名；预先规划也避免了多线程同时猜路径的竞态。
    """
    if opts.name_mode == "keep_extension":
        for it in items:
            if it.target is None:
                it.target = target_for(it.source, roots, opts, True)
        return

    groups: dict[Path, list[JobItem]] = {}
    for it in items:
        if it.target is not None:
            continue
        groups.setdefault(target_for(it.source, roots, opts, False), []).append(it)

    for base, group in groups.items():
        if len(group) == 1:
            group[0].target = base
            continue
        taken: set[Path] = set()
        for it in group:
            alt = target_for(it.source, roots, opts, True)
            n = 1
            while alt in taken:
                alt = _numbered(alt, n)
                n += 1
            taken.add(alt)
            it.target = alt


# --------------------------------------------------------------------------- #
# 转换执行
# --------------------------------------------------------------------------- #
def convert_one(md, source: Path, opts: ConvertOptions) -> str:
    result = md.convert(
        str(source),
        stream_info=new_stream_info(opts),
        keep_data_uris=bool(opts.keep_data_uris),
    )
    return result.markdown


def run_batch(
    items: list[JobItem],
    opts: ConvertOptions,
    roots: Iterable[Path],
    on_item: Callable[[JobItem], None] | None = None,
    on_start: Callable[[JobItem], None] | None = None,
    stop_flag: Callable[[], bool] | None = None,
) -> None:
    """在一个线程里跑完一整批：MarkItDown 实例（含 magika 模型）只初始化一次。"""
    if not items:
        return
    try:
        md = new_markitdown(opts)
    except Exception as exc:
        for it in items:
            it.status = "失败"
            it.message = f"初始化失败：{exc}"
            if on_item:
                on_item(it)
        return

    for it in items:
        if stop_flag and stop_flag():
            it.status = "已取消"
            it.message = "用户停止"
            if on_item:
                on_item(it)
            continue
        if on_start:
            on_start(it)
        started = time.monotonic()
        try:
            target = it.target or target_for(it.source, roots, opts, True)
            if target.exists() and opts.conflict == "skip":
                it.status = "跳过"
                it.message = "输出文件已存在"
                it.target = target
                if on_item:
                    on_item(it)
                continue
            if target.exists() and opts.conflict == "number":
                target = unique_path(target)
            text = convert_one(md, it.source, opts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            it.target = target
            it.chars = len(text)
            it.status = "完成"
            it.message = ""
        except Exception as exc:
            it.status = "失败"
            it.message = _first_line(exc)
        finally:
            it.elapsed = time.monotonic() - started
            if on_item:
                on_item(it)


def _first_line(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text.splitlines()[0][:300]
