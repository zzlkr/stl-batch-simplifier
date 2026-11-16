# STL 批量减面工具

Windows 桌面工具：批量简化 STL 三角网格，在同步的 OpenGL 视窗中对比原件与结果。可为选中的一个或多个零件单独调整参数，预览满意后再保存。

- 按保留比例或目标三角面数减面，支持边界、法线和拓扑等选项。
- 支持中文路径和文件名，可递归处理并保留目录结构。
- 默认保留约 10% 的三角面。原始 STL 保持不变；批量处理默认跳过输出目录中的同名文件。

![工作台：测试球体减面前后对比](docs/workbench.png)

Windows 10/11 64 位版本见 [v1.7.0 下载页](https://github.com/zzlkr/stl-batch-simplifier/releases/tag/v1.7.0)。

## 使用

选择输入和输出文件夹，设置参数后点击「批量处理」。如果只想尝试某几个零件，在左侧列表中单选或多选，修改参数后点「预览选中」。中间两个视窗会同步旋转和缩放。效果合适时点「应用所选预览」，把当前预览写入输出目录。应用预览会覆盖对应的输出 STL。

详细步骤和参数见 [使用说明](docs/使用说明.txt)。

## 从源码运行

在 Windows 10/11 64 位上使用 Python 3.12，在仓库根目录运行以下 PowerShell 命令：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe .\src\stl_batch_simplifier_qt.py
```

三维预览需要可用的 OpenGL。

## MeshLab 算法与致谢

本项目通过 PyMeshLab 调用 MeshLab 的 **Quadric Edge Collapse Decimation**（二次误差边折叠减面）滤镜。STL 批处理、文件导出、参数管理和双视窗对比由本项目的 Windows 界面提供。[MeshLab](https://github.com/cnr-isti-vclab/meshlab) · [滤镜参数文档](https://pymeshlab.readthedocs.io/en/latest/filter_list.html#meshing-decimation-quadric-edge-collapse)

感谢 PyMeshLab 作者 Alessandro Muntoni、Paolo Cignoni 及 MeshLab 贡献者。该滤镜基于 Michael Garland 与 Paul S. Heckbert 在 SIGGRAPH 1997 发表的《Surface Simplification Using Quadric Error Metrics》。[PyMeshLab 引用](https://doi.org/10.5281/zenodo.4438750) · [MeshLab 论文](https://doi.org/10.2312/LocalChapterEvents/ItalChap/ItalianChapConf2008/129-136) · [算法论文](https://www.cs.cmu.edu/~garland/Papers/quadrics.pdf)

## 许可证

本项目自有源码采用 GNU General Public License v3.0 only（`GPL-3.0-only`）。[许可证全文](LICENSE)

| 组件 | 本项目中的用途 | 许可证 |
| --- | --- | --- |
| PyMeshLab / MeshLab | 网格处理及二次误差边折叠滤镜 | [GNU GPL v3](https://github.com/cnr-isti-vclab/PyMeshLab/blob/main/LICENSE) · [MeshLab 许可文件](https://github.com/cnr-isti-vclab/meshlab/blob/main/LICENSE.txt) |
| PySide6 / Qt | Windows 界面和 OpenGL 控件 | [社区版 LGPL v3 / GPL v3，另有商业许可](https://doc.qt.io/qtforpython-6/commercial/index.html) |
| NumPy | 网格数据和数值计算 | [BSD 3-Clause](https://numpy.org/doc/stable/license.html)，附带组件按各自许可证 |
| PyInstaller | 将 Python 程序打包为 EXE | [GNU GPL v2 或更高版本，含打包例外](https://pyinstaller.org/en/stable/license.html)，部分文件采用 Apache 2.0 |

上表记录了主要第三方组件的许可证。Release 同时提供应用源码、许可证文本及构建配置。原始依赖版本见 [运行依赖](requirements.txt) 和 [构建依赖](requirements-build.txt)，打包依赖的对应源码见 [第三方许可与源码](docs/THIRD_PARTY_NOTICES.md)。

## 打包 EXE

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean .\STL_Batch_Simplifier.spec
```

生成位置：`dist\STL_Batch_Simplifier_v1.7.exe`。打包后的 EXE 可在 Windows 上运行，无需另外安装 Python 或 MeshLab。

## 验证

```powershell
.\.venv\Scripts\python.exe .\src\stl_batch_simplifier_qt.py --self-test
$env:PYTHONPATH = (Resolve-Path .\src).Path
.\.venv\Scripts\python.exe .\tests\verify_selected_parts.py
.\.venv\Scripts\python.exe .\tests\verify_draft_preview.py
.\.venv\Scripts\python.exe .\tests\verify_gl_preview.py
.\.venv\Scripts\python.exe .\tests\verify_workbench_layout.py
```

界面检查需在支持 OpenGL 的 Windows 桌面会话中运行。脚本自动生成测试球体，验证中文路径、选择性重做、临时预览的应用与放弃、OpenGL 绘制及窗口布局。样件和截图写到本地 `.test-artifacts/`。
