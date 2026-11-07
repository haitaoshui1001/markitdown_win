"""转换链路验收：真实调用 markitdown，覆盖各格式 + 三个提示参数 + 批量并发 + 重名策略。

    .venv\\Scripts\\python.exe scripts/verify_engine.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SAMPLES = ROOT / "samples"
WORK = ROOT / "work" / "verify"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  ← ' + detail}")
    if not ok:
        failures.append(f"{name}: {detail}")


def convert(src: Path, **opt_kwargs) -> str:
    from markitdown_gui.engine import ConvertOptions, convert_one, new_markitdown

    opts = ConvertOptions(**opt_kwargs)
    return convert_one(new_markitdown(opts), src, opts)


def main() -> int:
    if not (SAMPLES / "sample.pdf").exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_samples.py")], check=True)
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)

    expectations = {
        "sample.docx": ("季度总结", "转化率"),
        "sample.xlsx": ("销售额", "150"),
        "sample.pptx": ("产品路线图", "关键结论"),
        "sample.html": ("系统升级公告", "批量转换"),
        "sample.csv": ("姓名", "李四"),
        "sample.pdf": ("MarkItDown PDF sample page", "Second line"),
    }
    for name, needles in expectations.items():
        try:
            text = convert(SAMPLES / name)
        except Exception as exc:
            check(f"转换 {name}", False, repr(exc))
            continue
        missing = [n for n in needles if n not in text]
        check(f"转换 {name}", not missing, f"缺少关键字 {missing}；输出前 120 字：{text[:120]!r}")

    # -x 扩展名提示：无后缀文件
    plain = convert(SAMPLES / "sample_noext")
    hinted = convert(SAMPLES / "sample_noext", extension_hint=".pdf")
    check("无后缀文件 + 扩展名提示", "MarkItDown PDF sample page" in hinted, hinted[:120])
    print(f"      （不加提示时自动识别结果长度 {len(plain)}，前 60 字：{plain[:60]!r}）")

    # -c 字符集提示：GBK 文本
    gbk = convert(SAMPLES / "sample_gbk.txt", charset_hint="GB18030")
    check("字符集提示 GB18030", "会议纪要" in gbk and "灰度" in gbk, gbk[:120])

    # 非法参数应被 validate 拦住
    from markitdown_gui.engine import ConvertOptions, validate

    bad = ConvertOptions(use_cu=True, cu_endpoint="", use_docintel=True, docintel_endpoint="")
    check("参数校验拦截", len(validate(bad)) >= 2, str(validate(bad)))

    # 批量 + 并发 + 目录输出（重点验证同主名不同格式不会互相覆盖）
    from markitdown_gui.engine import JobItem, collect_sources, plan_jobs, run_batch

    opts = ConvertOptions(output_mode="folder", output_dir=str(WORK / "out"), max_workers=3)
    sources = collect_sources([], [SAMPLES], opts)
    check("文件夹扫描命中", len(sources) == 7, f"实际 {len(sources)}: {[s.name for s in sources]}")
    items = [JobItem(source=s) for s in sources]
    plan_jobs(items, [SAMPLES], opts)
    targets = [it.target for it in items]
    check("输出路径无重复", len(set(targets)) == len(targets), str(sorted(map(str, targets))))
    run_batch(items, opts, [SAMPLES])
    done = [it for it in items if it.status == "完成"]
    check("批量并发转换", len(done) == len(items), str([(it.source.name, it.status, it.message) for it in items if it.status != "完成"]))
    produced = sorted(p.name for p in (WORK / "out").glob("*.md"))
    check("输出文件落盘", len(produced) == len(items), f"实际 {produced}")
    print("      输出文件名:", produced)

    # 保留原扩展名命名
    opts_keep = opts.copy(name_mode="keep_extension", output_dir=str(WORK / "out_keep"))
    keep_items = [JobItem(source=s) for s in sources[:2]]
    plan_jobs(keep_items, [SAMPLES], opts_keep)
    run_batch(keep_items, opts_keep, [SAMPLES])
    check("keep_extension 命名", all(it.target.name.endswith((".pdf.md", ".csv.md", ".docx.md")) for it in keep_items), str([it.target.name for it in keep_items]))

    # 重名策略：number / skip —— 直接复用上面已落盘的输出路径
    existing = next(it.target for it in items if it.source == sources[0])
    opts_num = opts.copy(conflict="number")
    again = [JobItem(source=sources[0], target=existing)]
    run_batch(again, opts_num, [SAMPLES])
    check("重名加序号", again[0].status == "完成" and again[0].target.name.endswith("_1.md"), str(again[0].target))

    opts_skip = opts.copy(conflict="skip")
    skipped = [JobItem(source=sources[0], target=existing)]
    run_batch(skipped, opts_skip, [SAMPLES])
    check("重名跳过", skipped[0].status == "跳过", skipped[0].status + " " + skipped[0].message)

    print()
    if failures:
        print(f"共 {len(failures)} 项失败")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
