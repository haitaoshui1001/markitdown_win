"""验证打包产物：真实调用 dist/MarkItDownGUI/MarkItDownGUI.exe 做转换、离屏建窗、以及实际启动。

    .venv\\Scripts\\python.exe scripts/verify_exe.py
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "dist" / "MarkItDownGUI" / "MarkItDownGUI.exe"
SAMPLES = ROOT / "samples"
WORK = ROOT / "work" / "exe"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  ← ' + detail}")
    if not ok:
        failures.append(f"{name}: {detail}")


def read_log(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(没有生成日志文件)"


def ps(command: str) -> str:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return (out.stdout or "").strip()


def selftest(sample: str, args: list[str] = []) -> tuple[bool, str, str]:
    src = SAMPLES / sample
    dst = WORK / f"{sample}.out.md"
    log = Path(str(dst) + ".selftest.log")
    if log.exists():
        log.unlink()
    proc = subprocess.run([str(EXE), "--selftest", str(src), str(dst), *args], timeout=180)
    text = read_log(log)
    ok = proc.returncode == 0 and text.startswith("SELFTEST_OK") and dst.exists()
    return ok, text, dst.read_text(encoding="utf-8") if dst.exists() else ""


def main() -> int:
    if not EXE.exists():
        print(f"找不到 {EXE}，先跑 pyinstaller build.spec")
        return 2
    WORK.mkdir(parents=True, exist_ok=True)

    size_mb = sum(p.stat().st_size for p in (ROOT / "dist" / "MarkItDownGUI").rglob("*") if p.is_file()) / 1e6
    print(f"产物：{EXE}  整包 {size_mb:.1f} MB")

    cases = {
        "sample.pdf": "MarkItDown PDF sample page",
        "sample.docx": "季度总结",
        "sample.xlsx": "销售额",
        "sample.pptx": "产品路线图",
        "sample.html": "系统升级公告",
        "sample.csv": "李四",
    }
    for sample, needle in cases.items():
        try:
            ok, log, text = selftest(sample)
        except subprocess.TimeoutExpired:
            check(f"exe 转换 {sample}", False, "180 秒超时")
            continue
        check(f"exe 转换 {sample}", ok and needle in text, f"{log[:160]} | 输出前 80 字 {text[:80]!r}")

    # 扩展名提示参数在冻结环境里同样生效
    ok, log, text = selftest("sample_noext", [])
    check("exe 转换无后缀文件", ok and "MarkItDown PDF sample page" in text, log[:200])

    # 真实启动：窗口标题应出现且进程存活
    proc = subprocess.Popen([str(EXE)])
    time.sleep(8)
    alive = ps(f"if (Get-Process -Id {proc.pid} -ErrorAction SilentlyContinue) {{ 'ALIVE' }}")
    title = ps(f"(Get-Process -Id {proc.pid} -ErrorAction SilentlyContinue).MainWindowTitle")
    check("exe 真实启动后进程存活", alive == "ALIVE", f"alive={alive!r} rc={proc.poll()}")
    check("exe 窗口标题正确", "MarkItDown" in title, f"title={title!r}")
    if alive == "ALIVE":
        ps(f"Stop-Process -Id {proc.pid} -Force")

    print()
    if failures:
        print(f"共 {len(failures)} 项失败：")
        for f in failures:
            print("  -", f)
        return 1
    print("exe 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
