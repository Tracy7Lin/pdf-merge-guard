# PDF Merge Guard

PDF Merge Guard 是一个面向 Windows 10/11 的离线桌面工具。它可以按指定顺序合并多个 PDF，并在双面打印时确保下一份文件从新纸张开始。

## 功能

- 拖动调整 PDF 顺序，显示每份文件的页数和完整路径。
- “双面打印隔离”模式会在非最后一份奇数页文件后补充空白页。
- “普通合并”模式不添加任何页面。
- 输出文件名和目录均可修改；覆盖已有文件前会明确确认。
- 简体中文/英文即时切换，并记忆语言选择。
- 完全离线运行，不需要 Microsoft Office。

## 使用预构建程序

运行 `dist\PDF Merge Guard.exe`。添加至少两个 PDF，拖动调整顺序，选择合并方式和保存位置，然后点击“开始合并”。

加密、损坏、空白或无法读取的 PDF 会阻止本次任务，并在界面中列出。程序先写入临时文件，仅在成功后替换目标文件。

## 开发与测试

需要 Python 3.11–3.13：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
.\test.ps1
```

本机启动：

```powershell
$env:PYTHONPATH = "src"
python -m pdf_merge_guard
```

## 构建单文件 EXE

安装开发依赖后运行：

```powershell
.\build.ps1
```

产物位于 `dist\PDF Merge Guard.exe`。首次启动单文件程序时，PyInstaller 需要解压运行组件，因此可能比后续操作稍慢。

## 限制

- 仅支持 PDF，不负责将 Word、PPT、图片或文本转换为 PDF。
- 不支持输入加密 PDF 的密码。
- 合并会改变 PDF 文件结构，原有数字签名通常不再有效。

## 许可证

项目代码采用 MIT License。运行时包含的 PySide6/Qt 和 pypdf 受其各自许可证约束；分发程序时请同时遵守对应许可条款。

