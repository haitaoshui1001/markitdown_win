"""生成用于验证转换链路的样例文件：docx/xlsx/pptx/html/csv/txt/legacy 无扩展名/pdf。"""

from __future__ import annotations

import sys
from pathlib import Path

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("samples")
OUT.mkdir(parents=True, exist_ok=True)


def make_docx(path: Path) -> None:
    from docx import Document

    doc = Document()
    doc.add_heading("季度总结", level=1)
    doc.add_paragraph("这是第一段正文，包含一个粗体片段。")
    doc.add_paragraph("项目 A 完成率 92%，项目 B 因为依赖方延期顺延两周。")
    table = doc.add_table(rows=2, cols=3)
    for i, h in enumerate(("指标", "目标", "实际")):
        table.rows[0].cells[i].text = h
    for i, v in enumerate(("转化率", "3.0%", "3.4%")):
        table.rows[1].cells[i].text = v
    doc.save(path)


def make_xlsx(path: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "销售"
    ws.append(["月份", "销售额", "同比"])
    for row in ([1, 120, "5%"], [2, 150, "12%"], [3, 98, "-4%"]):
        ws.append(row)
    wb.save(path)


def make_pptx(path: Path) -> None:
    from pptx import Presentation

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "产品路线图"
    slide.placeholders[1].text = "Q1 打通转换链路\nQ2 支持批量与插件"
    body = prs.slides.add_slide(prs.slide_layouts[1])
    body.shapes.title.text = "关键结论"
    body.shapes.placeholders[1].text = "离线转换可用\n云端方案按需接入"
    prs.save(path)


def make_html(path: Path) -> None:
    path.write_text(
        """<!doctype html><html><head><title>公告</title></head><body>
        <h1>系统升级公告</h1><p>本次升级新增 <strong>批量转换</strong>。</p>
        <ul><li>支持拖拽</li><li>支持文件夹扫描</li></ul>
        <table><tr><th>参数</th><th>含义</th></tr><tr><td>-x</td><td>扩展名提示</td></tr></table>
        </body></html>""",
        encoding="utf-8",
    )


def make_csv(path: Path) -> None:
    path.write_text("姓名,部门,绩效\n张三,研发,A\n李四,产品,B+\n", encoding="utf-8")


def make_txt_gbk(path: Path) -> None:
    """故意用 GBK 编码且无标准内容头，用来验证字符集提示参数。"""
    path.write_bytes("会议纪要：确认下周一发布。\n第二条：需要灰度。\n".encode("gb18030"))


def make_pdf(path: Path) -> None:
    content = b"BT /F1 20 Tf 40 700 Td (MarkItDown PDF sample page) Tj ET\n"
    content += b"BT /F1 12 Tf 40 670 Td (Second line of body text.) Tj ET"
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>",
        b"<</Length " + str(len(content)).encode() + b">>\nstream\n" + content + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


def main() -> None:
    targets = {
        "sample.docx": make_docx,
        "sample.xlsx": make_xlsx,
        "sample.pptx": make_pptx,
        "sample.html": make_html,
        "sample.csv": make_csv,
        "sample_gbk.txt": make_txt_gbk,
        "sample.pdf": make_pdf,
    }
    for name, fn in targets.items():
        fn(OUT / name)
        print("生成", OUT / name)

    # 无扩展名副本：用来验证「扩展名提示 -x」参数是否真的生效
    import shutil

    shutil.copyfile(OUT / "sample.pdf", OUT / "sample_noext")
    print("样例目录：", OUT.resolve())


if __name__ == "__main__":
    main()
