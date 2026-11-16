# STL 批量减面工具 v1.7.0 的依赖源码与许可

此清单对应 Windows x64 文件 `STL_Batch_Simplifier_v1.7.exe`。

- 文件大小为 116374522 字节。
- SHA-256 为 `e737c23b8d44f980aac973fa38c840ab7992b91af0a03b7758f860b09dcc3a0c`。
- 应用代码对应标签 `v1.7.0`。Release 提供包含应用源代码、构建配置及许可证的 `STL_Batch_Simplifier_v1.7.0-source.zip`。构建命令见包内 README，依赖版本见 requirements.txt 和 requirements-build.txt。

| 组件 | 对应版本 | 上游源码或许可证 |
| --- | --- | --- |
| PyMeshLab | 2025.7.post1 | [版本源码与构建脚本](https://github.com/cnr-isti-vclab/PyMeshLab/tree/v2025.7.post1)，GNU GPL v3 |
| MeshLab 滤镜 | PyMeshLab 同版本锁定的子模块 | [MeshLab 锁定提交](https://github.com/cnr-isti-vclab/meshlab/tree/d876376e3cc4f92d257e248023d82cbac5b03c7d) · [原生依赖及编译配置](https://github.com/cnr-isti-vclab/meshlab/tree/d876376e3cc4f92d257e248023d82cbac5b03c7d/src/external)，GNU GPL v3 |
| Qt 5 | 5.15.2，随 PyMeshLab 分发 | [源码归档](https://download.qt.io/archive/qt/5.15/5.15.2/submodules/)，各模块许可见对应源码包 |
| PySide6 / Shiboken6 | 6.11.2 | [版本源码](https://github.com/pyside/pyside-setup/tree/v6.11.2) · [Qt for Python 许可证](https://doc.qt.io/qtforpython-6/licenses.html) |
| Qt 6 | 6.11.2，随 PySide6 分发 | [源码归档](https://download.qt.io/archive/qt/6.11/6.11.2/submodules/)，各模块许可见对应源码包 |
| NumPy | 2.5.2 | [版本源码](https://github.com/numpy/numpy/tree/v2.5.2) · [许可证](https://numpy.org/doc/stable/license.html)，含随 wheel 分发的组件声明 |
| CPython | 3.12.14 | [版本源码](https://www.python.org/downloads/release/python-31214/) · [PSF 许可](https://docs.python.org/3.12/license.html) |
| PyInstaller | 6.22.2 | [版本源码](https://github.com/pyinstaller/pyinstaller/tree/v6.22.2) · [GPL 及打包例外](https://pyinstaller.org/en/stable/license.html) |

包内 `third-party-licenses/` 提供 GPLv3、LGPLv3、Python 以及 NumPy wheel 随附的许可文本。PyMeshLab 包内的原生插件依赖及版本由其锁定的 MeshLab 构建配置记录。Windows 运行库适用微软的再分发条款。[Microsoft Visual C++ 运行库说明](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files)

如需用修改过的依赖重建 EXE，在虚拟环境安装对应的替换版本，再按 README 使用同一 PyInstaller 配置打包。重新构建时应保留相关依赖的许可声明。

PyMeshLab 的源码检出包含 MeshLab 和 pybind11 子模块。

```sh
git clone --branch v2025.7.post1 --recurse-submodules https://github.com/cnr-isti-vclab/PyMeshLab.git
```
