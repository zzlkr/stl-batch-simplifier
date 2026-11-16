from __future__ import annotations

import os
import math
import shutil
import struct
import sys
import tempfile
import traceback
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import (
    QBrush,
    QCloseEvent,
    QColor,
    QDesktopServices,
    QFont,
    QMouseEvent,
    QPainter,
    QPen,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QSpinBox,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "STL 批量减面工具"
APP_VERSION = "1.7.0"


@dataclass(frozen=True)
class SimplifyOptions:
    target_mode: str
    target_faces: int
    retain_percent: float
    quality_threshold: float
    preserve_boundary: bool
    boundary_weight: float
    preserve_normal: bool
    preserve_topology: bool
    optimal_placement: bool
    planar_simplification: bool
    planar_weight: float
    weighted_simplification: bool
    post_cleaning: bool


@dataclass(frozen=True)
class DraftResult:
    path: Path
    options: SimplifyOptions
    before: int
    after: int
    source_signature: tuple[int, int]


def import_meshlab():
    try:
        import pymeshlab  # type: ignore

        return pymeshlab
    except Exception as exc:
        raise RuntimeError("无法加载 PyMeshLab 网格处理引擎，请重新下载完整程序。") from exc


def save_binary_stl_unicode_safe(mesh, destination: Path) -> None:
    """Write a binary STL using Python file I/O, which fully supports Unicode paths.

    PyMeshLab's Windows STL exporter cannot open some paths containing CJK
    characters. Reading vertex/face arrays and writing the simple binary STL
    structure ourselves avoids that exporter limitation without changing geometry.
    """
    import numpy as np

    vertices = np.asarray(mesh.vertex_matrix())
    faces = np.asarray(mesh.face_matrix(), dtype=np.int64)
    face_count = int(faces.shape[0])
    if face_count <= 0:
        raise RuntimeError("减面后的网格没有可导出的三角面")
    if face_count > 0xFFFFFFFF:
        raise RuntimeError("三角面数量超过二进制 STL 格式上限")
    if vertices.ndim != 2 or vertices.shape[1] != 3 or faces.ndim != 2 or faces.shape[1] != 3:
        raise RuntimeError("当前网格不是有效的三角网格")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.stem + ".processing.stl")
    record_dtype = np.dtype(
        [
            ("normal", "<f4", (3,)),
            ("v1", "<f4", (3,)),
            ("v2", "<f4", (3,)),
            ("v3", "<f4", (3,)),
            ("attribute", "<u2"),
        ],
        align=False,
    )
    if record_dtype.itemsize != 50:
        raise RuntimeError("内部 STL 记录格式错误")

    try:
        if temporary.exists():
            temporary.unlink()
        with temporary.open("wb") as stream:
            header_text = f"{APP_NAME} v{APP_VERSION}".encode("ascii", errors="replace")[:80]
            stream.write(header_text.ljust(80, b" "))
            stream.write(struct.pack("<I", face_count))

            # Chunking keeps peak memory reasonable for very large meshes.
            chunk_size = 100_000
            for start in range(0, face_count, chunk_size):
                stop = min(start + chunk_size, face_count)
                triangles = vertices[faces[start:stop]]
                normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
                lengths = np.linalg.norm(normals, axis=1)
                valid = lengths > 1e-30
                normals[valid] /= lengths[valid, None]
                normals[~valid] = 0

                records = np.zeros(stop - start, dtype=record_dtype)
                records["normal"] = normals
                records["v1"] = triangles[:, 0]
                records["v2"] = triangles[:, 1]
                records["v3"] = triangles[:, 2]
                stream.write(records.tobytes(order="C"))
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def simplify_one(source: Path, destination: Path, options: SimplifyOptions) -> tuple[int, int, str]:
    pymeshlab = import_meshlab()
    mesh_set = pymeshlab.MeshSet()
    mesh_set.load_new_mesh(str(source))
    before = int(mesh_set.current_mesh().face_number())
    if before <= 0:
        raise ValueError("文件中没有可处理的三角面")

    if options.target_mode == "faces":
        no_reduction_needed = options.target_faces >= before
    else:
        no_reduction_needed = options.retain_percent >= 100.0

    destination.parent.mkdir(parents=True, exist_ok=True)
    if no_reduction_needed:
        shutil.copy2(source, destination)
        return before, before, "目标不小于原面数，已原样复制"

    common_args = dict(
        qualitythr=options.quality_threshold,
        preserveboundary=options.preserve_boundary,
        boundaryweight=options.boundary_weight,
        preservenormal=options.preserve_normal,
        preservetopology=options.preserve_topology,
        optimalplacement=options.optimal_placement,
        planarquadric=options.planar_simplification,
        planarweight=options.planar_weight,
        qualityweight=options.weighted_simplification,
        autoclean=options.post_cleaning,
        selected=False,
    )
    if options.target_mode == "faces":
        mesh_set.apply_filter(
            "meshing_decimation_quadric_edge_collapse",
            targetfacenum=options.target_faces,
            **common_args,
        )
    else:
        mesh_set.apply_filter(
            "meshing_decimation_quadric_edge_collapse",
            targetperc=options.retain_percent / 100.0,
            **common_args,
        )

    after = int(mesh_set.current_mesh().face_number())
    if after <= 0:
        raise RuntimeError("减面后网格为空，未写入输出文件")

    save_binary_stl_unicode_safe(mesh_set.current_mesh(), destination)
    return before, after, "完成"


def find_stl_files(source: Path, recursive: bool, output: Path | None = None) -> list[Path]:
    iterator = source.rglob("*") if recursive else source.glob("*")
    output_resolved = output.resolve() if output else None
    files: list[Path] = []
    for path in iterator:
        if not path.is_file() or path.suffix.lower() != ".stl":
            continue
        if output_resolved:
            try:
                path.resolve().relative_to(output_resolved)
                continue
            except ValueError:
                pass
        files.append(path)
    return sorted(files, key=lambda item: str(item).lower())


@dataclass(frozen=True)
class PreviewData:
    triangles: object
    face_count: int


def load_stl_preview(path: Path) -> PreviewData:
    """Load complete STL geometry; dropping triangles creates visible holes."""
    import numpy as np

    if not path.is_file():
        raise FileNotFoundError("文件尚未生成")
    size = path.stat().st_size
    if size < 15:
        raise ValueError("STL 文件为空或不完整")

    binary_count = -1
    with path.open("rb") as stream:
        header = stream.read(84)
        if len(header) == 84:
            binary_count = struct.unpack("<I", header[80:84])[0]

    if binary_count >= 0 and 84 + binary_count * 50 == size:
        record_dtype = np.dtype(
            [
                ("normal", "<f4", (3,)),
                ("v1", "<f4", (3,)),
                ("v2", "<f4", (3,)),
                ("v3", "<f4", (3,)),
                ("attribute", "<u2"),
            ],
            align=False,
        )
        with path.open("rb") as stream:
            stream.seek(84)
            records = np.fromfile(stream, dtype=record_dtype, count=binary_count)
        if len(records) != binary_count:
            raise ValueError("二进制 STL 数据不完整")
        if binary_count:
            triangles = np.stack((records["v1"], records["v2"], records["v3"]), axis=1)
        else:
            triangles = np.empty((0, 3, 3), dtype=np.float32)
        face_count = binary_count
    else:
        vertices: list[tuple[float, float, float]] = []
        with path.open("r", encoding="utf-8", errors="ignore") as stream:
            for line in stream:
                parts = line.strip().split()
                if len(parts) >= 4 and parts[0].lower() == "vertex":
                    try:
                        vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
                    except ValueError:
                        continue
        face_count = len(vertices) // 3
        if face_count <= 0:
            raise ValueError("无法识别 STL 三角面")
        triangles = np.asarray(vertices[: face_count * 3], dtype=np.float32).reshape((-1, 3, 3))

    if face_count <= 0:
        raise ValueError("STL 中没有三角面")
    return PreviewData(np.asarray(triangles, dtype=np.float32), face_count)


from mesh_preview_gl import MeshPreviewWidget


class PreviewLoaderThread(QThread):
    loaded = Signal(int, object, object, str, str)

    def __init__(self, token: int, original: Path, simplified: Path | None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.token = token
        self.original = original
        self.simplified = simplified

    def run(self) -> None:
        before = None
        after = None
        before_error = ""
        after_error = ""
        try:
            before = load_stl_preview(self.original)
        except Exception as exc:
            before_error = str(exc)
        if self.simplified and self.simplified.is_file():
            try:
                after = load_stl_preview(self.simplified)
            except Exception as exc:
                after_error = str(exc)
        else:
            after_error = "等待处理完成"
        self.loaded.emit(self.token, before, after, before_error, after_error)


class BatchWorker(QObject):
    status = Signal(int, int, str)
    progress = Signal(int, int)
    log = Signal(str)
    file_started = Signal(str)
    file_result = Signal(str, int, int, str, str)
    completed = Signal(int, int, int, int, str)
    cancelled = Signal(int, int, int, int)

    def __init__(
        self,
        source_root: Path,
        output_root: Path,
        files: list[Path],
        options: SimplifyOptions,
        overwrite: bool,
        recursive: bool,
    ) -> None:
        super().__init__()
        self.source_root = source_root
        self.output_root = output_root
        self.files = files
        self.options = options
        self.overwrite = overwrite
        self.recursive = recursive
        self.cancel_requested = False

    @Slot()
    def request_cancel(self) -> None:
        self.cancel_requested = True

    @Slot()
    def run(self) -> None:
        succeeded = 0
        skipped = 0
        failed = 0
        total = len(self.files)
        for index, source in enumerate(self.files, start=1):
            if self.cancel_requested:
                self.cancelled.emit(succeeded, skipped, failed, total)
                return
            relative = source.relative_to(self.source_root)
            destination = self.output_root / relative if self.recursive else self.output_root / source.name
            self.status.emit(index - 1, total, f"正在处理：{relative}")
            relative_key = relative.as_posix()
            self.file_started.emit(relative_key)
            if destination.exists() and not self.overwrite:
                skipped += 1
                self.log.emit(f"[跳过] {relative}：输出文件已存在")
                self.file_result.emit(relative_key, 0, 0, "已跳过", str(destination))
                self.progress.emit(index, total)
                continue
            try:
                before, after, note = simplify_one(source, destination, self.options)
                succeeded += 1
                reduction = (1.0 - after / before) * 100.0 if before else 0.0
                self.log.emit(
                    f"[完成] {relative}：{before:,} → {after:,} 面，减少 {reduction:.1f}%（{note}）"
                )
                self.file_result.emit(relative_key, before, after, "完成", str(destination))
            except Exception as exc:
                failed += 1
                self.log.emit(f"[失败] {relative}：{exc}")
                self.file_result.emit(relative_key, 0, 0, f"失败：{exc}", str(destination))
            self.progress.emit(index, total)
        self.completed.emit(succeeded, skipped, failed, total, str(self.output_root))


class MainWindow(QMainWindow):
    cancel_signal = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  v{APP_VERSION}")
        self.resize(1380, 800)
        self.setMinimumSize(960, 560)
        self.thread: QThread | None = None
        self.worker: BatchWorker | None = None
        self.last_output: Path | None = None
        self.file_items: dict[str, QTreeWidgetItem] = {}
        self.part_options: dict[tuple[str, str], SimplifyOptions] = {}
        self.active_options: SimplifyOptions | None = None
        self.drafts: dict[tuple[str, str], DraftResult] = {}
        self.draft_directories: list[tempfile.TemporaryDirectory] = []
        self.preview_only = False
        self.busy = False
        self.active_source_root: Path | None = None
        self.active_output_root: Path | None = None
        self.active_signatures: dict[str, tuple[int, int]] = {}
        self.preview_threads: set[PreviewLoaderThread] = set()
        self.preview_token = 0
        self._build_ui()
        self.restore_defaults()

    def _build_ui(self) -> None:
        central = QWidget(objectName="workbench")
        self.setCentralWidget(central)
        page = QVBoxLayout(central)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)

        def strip(name):
            panel = QWidget(objectName=name)
            layout = QHBoxLayout(panel)
            layout.setContentsMargins(9, 5, 9, 5)
            layout.setSpacing(6)
            return panel, layout

        def separator(layout):
            line = QFrame()
            line.setFrameShape(QFrame.Shape.VLine)
            line.setObjectName("divider")
            layout.addWidget(line)

        command_bar, commands = strip("commandBar")
        folder_toggle = QPushButton("文件夹 ▾", objectName="folderToggle")
        folder_toggle.setCheckable(True)
        folder_toggle.setChecked(True)
        folders = QWidget(objectName="folderPanel")
        self.folders_group = folders
        folder_grid = QGridLayout(folders)
        folder_grid.setContentsMargins(12, 6, 12, 6)
        folder_grid.setColumnStretch(1, 1)
        self.input_edit = QLineEdit()
        self.output_edit = QLineEdit()
        input_button = QPushButton("浏览…")
        output_button = QPushButton("浏览…")
        input_button.clicked.connect(self.choose_input)
        output_button.clicked.connect(self.choose_output)
        folder_grid.addWidget(QLabel("输入文件夹："), 0, 0)
        folder_grid.addWidget(self.input_edit, 0, 1)
        folder_grid.addWidget(input_button, 0, 2)
        folder_grid.addWidget(QLabel("输出文件夹："), 1, 0)
        folder_grid.addWidget(self.output_edit, 1, 1)
        folder_grid.addWidget(output_button, 1, 2)
        self.recursive_check = QCheckBox("包含子文件夹并保留目录结构")
        self.overwrite_check = QCheckBox("覆盖输出目录中的同名文件")
        option_row = QHBoxLayout()
        option_row.addWidget(self.recursive_check)
        option_row.addSpacing(20)
        option_row.addWidget(self.overwrite_check)
        option_row.addStretch(1)
        folder_grid.addLayout(option_row, 2, 0, 1, 3)
        self.file_count_label = QLabel("请选择包含 STL 文件的输入文件夹")
        self.file_count_label.setStyleSheet("color: #5d6673;")
        self.input_edit.editingFinished.connect(self.refresh_file_count)
        self.output_edit.editingFinished.connect(self.refresh_file_count)
        self.recursive_check.toggled.connect(self.refresh_file_count)
        folder_toggle.toggled.connect(folders.setVisible)
        folder_toggle.toggled.connect(lambda shown: folder_toggle.setText("文件夹 ▾" if shown else "文件夹 ▸"))

        self.start_button = QPushButton("批量处理")
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.selected_button = QPushButton("重做选中（0）")
        self.selected_button.setEnabled(False)
        self.selected_button.setToolTip("使用右侧参数，从原始 STL 重新减面；覆盖选中零件的输出文件。")
        self.selected_button.clicked.connect(self.start_selected)
        self.load_part_options_button = QPushButton("载入零件参数")
        self.load_part_options_button.setEnabled(False)
        self.load_part_options_button.clicked.connect(self.load_part_options)
        defaults_button = QPushButton("恢复默认")
        self.open_output_button = QPushButton("打开输出")
        self.open_output_button.setEnabled(False)
        self.start_button.clicked.connect(self.start_batch)
        self.cancel_button.clicked.connect(self.cancel_batch)
        defaults_button.clicked.connect(self.restore_defaults)
        self.open_output_button.clicked.connect(self.open_output_folder)

        self.preview_selected_button = QPushButton("预览选中", objectName="previewAction")
        self.apply_preview_button = QPushButton("应用所选预览")
        self.discard_preview_button = QPushButton("放弃预览")
        self.preview_selected_button.setToolTip("从原始 STL 临时减面，仅更新右侧预览；不修改输出文件。")
        self.apply_preview_button.setToolTip("将选中零件已显示的预览结果保存到输出文件夹，覆盖对应 STL。")
        self.preview_selected_button.clicked.connect(self.start_preview)
        self.apply_preview_button.clicked.connect(self.apply_selected_previews)
        self.discard_preview_button.clicked.connect(self.discard_selected_previews)
        for button in (self.preview_selected_button, self.apply_preview_button, self.discard_preview_button):
            button.setEnabled(False)

        commands.addWidget(folder_toggle)
        separator(commands)
        for button in (self.start_button, self.selected_button, self.preview_selected_button):
            commands.addWidget(button)
        separator(commands)
        commands.addWidget(self.apply_preview_button)
        commands.addWidget(self.discard_preview_button)
        commands.addStretch()
        commands.addWidget(self.open_output_button)
        commands.addWidget(self.cancel_button)
        page.addWidget(command_bar)
        page.addWidget(folders)

        work_area = QSplitter(Qt.Orientation.Horizontal, objectName="workArea")
        work_area.setChildrenCollapsible(False)
        page.addWidget(work_area, 1)

        part_panel = QWidget(objectName="sidePanel")
        part_panel.setMinimumWidth(184)
        parts = QVBoxLayout(part_panel)
        parts.setContentsMargins(0, 0, 0, 0)
        parts.setSpacing(0)
        part_header, part_tools = strip("dockTitle")
        part_tools.addWidget(QLabel("零件列表"))
        part_tools.addStretch()
        detail_toggle = QToolButton()
        detail_toggle.setText("详细列")
        detail_toggle.setCheckable(True)
        detail_toggle.setToolTip("查看原始面数、结果面数、减面率和使用参数")
        part_tools.addWidget(detail_toggle)
        parts.addWidget(part_header)
        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderLabels(["零件", "原始面", "简化后", "减少", "状态", "使用参数"])
        self.file_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_tree.setAlternatingRowColors(True)
        self.file_tree.setRootIsDecorated(False)
        self.file_tree.setUniformRowHeights(True)
        self.file_tree.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.file_tree.header().setStretchLastSection(False)
        for column in range(1, 6):
            self.file_tree.header().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.file_tree.header().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.file_tree.header().resizeSection(4, 98)

        def show_detail(shown):
            self.file_tree.header().setSectionResizeMode(
                0, QHeaderView.ResizeMode.ResizeToContents if shown else QHeaderView.ResizeMode.Stretch)
            for column in (1, 2, 3, 5):
                self.file_tree.setColumnHidden(column, not shown)
        show_detail(False)
        detail_toggle.toggled.connect(show_detail)
        self.file_tree.itemSelectionChanged.connect(self.on_part_selected)
        self.file_tree.currentItemChanged.connect(lambda *_: self.on_part_selected())
        parts.addWidget(self.file_tree, 1)
        self.file_count_label.setWordWrap(True)
        self.file_count_label.setObjectName("treeFooter")
        self.file_count_label.setToolTip("Ctrl 或 Shift 可多选零件")
        parts.addWidget(self.file_count_label)
        work_area.addWidget(part_panel)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        preview_page = QWidget()
        preview_layout = QVBoxLayout(preview_page)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)
        view_header, view_tools = strip("dockTitle")
        self.current_part_label = QLabel("未选择零件")
        self.current_part_label.setTextFormat(Qt.TextFormat.PlainText)
        self.current_part_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        view_tools.addWidget(self.current_part_label, 1)
        view_tools.addWidget(QLabel("同步视角"))
        comparison = QSplitter(Qt.Orientation.Horizontal, objectName="viewDivider")
        comparison.setChildrenCollapsible(False)
        self.before_preview = MeshPreviewWidget("原始模型", "#b9bec6")
        self.after_preview = MeshPreviewWidget("简化后", "#b9bec6")
        for preview in (self.before_preview, self.after_preview):
            preview.setMinimumWidth(244)
            comparison.addWidget(preview)
        self.before_preview.view_changed.connect(self.after_preview.set_view)
        self.after_preview.view_changed.connect(self.before_preview.set_view)
        reset_view = QPushButton("复位视角")
        reset_view.clicked.connect(self.before_preview.reset_view)
        view_tools.addWidget(reset_view)
        preview_layout.addWidget(view_header)
        preview_layout.addWidget(comparison, 1)
        comparison.setSizes([455, 455])
        self.tabs.addTab(preview_page, "模型对比")
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setFont(QFont("Consolas", 9))
        self.tabs.addTab(self.log_edit, "处理日志")
        work_area.addWidget(self.tabs)

        property_panel = QWidget(objectName="sidePanel")
        property_panel.setMinimumWidth(215)
        inspector = QVBoxLayout(property_panel)
        inspector.setContentsMargins(0, 0, 0, 0)
        inspector.setSpacing(0)
        inspector_header, inspector_title = strip("dockTitle")
        inspector_title.addWidget(QLabel("减面属性"))
        inspector_title.addStretch()
        inspector.addWidget(inspector_header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.settings_group = QWidget(objectName="propertyBody")
        scroll.setWidget(self.settings_group)
        inspector.addWidget(scroll, 1)
        sections = QVBoxLayout(self.settings_group)
        sections.setContentsMargins(0, 0, 0, 0)
        sections.setSpacing(0)

        def section(name, expanded):
            toggle = QToolButton(objectName="propertySection")
            toggle.setText(name)
            toggle.setCheckable(True)
            toggle.setChecked(expanded)
            toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
            toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            body = QWidget()
            grid = QGridLayout(body)
            grid.setContentsMargins(10, 6, 10, 8)
            grid.setColumnStretch(1, 1)
            toggle.toggled.connect(body.setVisible)
            toggle.toggled.connect(lambda shown: toggle.setArrowType(
                Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow))
            body.setVisible(expanded)
            sections.addWidget(toggle)
            sections.addWidget(body)
            return grid

        def property_row(grid, row, text, editor):
            label = QLabel(text)
            label.setBuddy(editor)
            grid.addWidget(label, row, 0)
            grid.addWidget(editor, row, 1)

        targets = section("减面目标", True)
        self.faces_radio = QRadioButton("目标面数")
        self.percent_radio = QRadioButton("保留比例")
        self.target_faces_spin = QSpinBox()
        self.target_faces_spin.setRange(1, 100_000_000)
        self.target_faces_spin.setGroupSeparatorShown(True)
        self.retain_spin = QDoubleSpinBox()
        self.retain_spin.setRange(0.01, 100.0)
        self.retain_spin.setDecimals(2)
        self.retain_spin.setSuffix(" %")
        self.retain_spin.setToolTip("10% 表示保留约十分之一的三角面")
        targets.addWidget(self.percent_radio, 0, 0)
        targets.addWidget(self.retain_spin, 0, 1)
        targets.addWidget(self.faces_radio, 1, 0)
        targets.addWidget(self.target_faces_spin, 1, 1)
        self.faces_radio.toggled.connect(self.update_target_state)
        self.quality_spin = QDoubleSpinBox()
        self.quality_spin.setRange(0, 1)
        self.quality_spin.setDecimals(3)
        self.quality_spin.setSingleStep(0.05)
        self.quality_spin.setToolTip("0～1；值越高越抑制狭长、畸形三角面")
        property_row(targets, 2, "质量阈值", self.quality_spin)

        constraints = section("几何约束", True)
        self.preserve_boundary_check = QCheckBox("保留网格边界")
        self.preserve_normal_check = QCheckBox("保持法线")
        self.preserve_topology_check = QCheckBox("保持拓扑")
        for row, check in enumerate((self.preserve_boundary_check, self.preserve_normal_check,
                                     self.preserve_topology_check)):
            constraints.addWidget(check, row, 0, 1, 2)

        advanced = section("高级参数", False)
        self.boundary_weight_spin = QDoubleSpinBox()
        self.boundary_weight_spin.setRange(0, 1_000_000)
        self.boundary_weight_spin.setDecimals(4)
        property_row(advanced, 0, "边界权重", self.boundary_weight_spin)
        self.planar_weight_spin = QDoubleSpinBox()
        self.planar_weight_spin.setRange(0, 1_000_000)
        self.planar_weight_spin.setDecimals(6)
        self.planar_weight_spin.setSingleStep(0.001)
        property_row(advanced, 1, "平面权重", self.planar_weight_spin)
        self.optimal_check = QCheckBox("最优顶点位置")
        self.planar_check = QCheckBox("平面区域简化")
        self.weighted_check = QCheckBox("按三角面质量加权")
        self.clean_check = QCheckBox("简化后自动清理")
        for row, check in enumerate((self.optimal_check, self.planar_check, self.weighted_check,
                                     self.clean_check), start=2):
            advanced.addWidget(check, row, 0, 1, 2)

        summary = section("当前零件", True)
        self.part_stat_labels = [QLabel("—") for _ in range(3)]
        for row, title in enumerate(("原始面数", "结果面数", "减少比例")):
            self.part_stat_labels[row].setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            property_row(summary, row, title, self.part_stat_labels[row])
        sections.addStretch()
        inspector_footer, inspector_commands = strip("propertyFooter")
        inspector_commands.addWidget(self.load_part_options_button, 1)
        inspector_commands.addWidget(defaults_button)
        inspector.addWidget(inspector_footer)
        work_area.addWidget(property_panel)
        for index, stretch in enumerate((0, 1, 0)):
            work_area.setStretchFactor(index, stretch)
        work_area.setSizes([236, 885, 249])

        status, status_items = strip("statusBar")
        self.selection_label = QLabel("选中 0 件")
        self.draft_count_label = QLabel("待应用 0 件", objectName="pendingText")
        self.progress_label = QLabel("就绪")
        self.progress_label.setTextFormat(Qt.TextFormat.PlainText)
        self.progress_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFixedWidth(112)
        self.progress.setMaximumHeight(14)
        status_items.addWidget(self.selection_label)
        status_items.addWidget(self.draft_count_label)
        separator(status_items)
        status_items.addWidget(self.progress_label, 1)
        status_items.addWidget(self.progress)
        page.addWidget(status)

        central.setStyleSheet("""
            QWidget#workbench { background: #f2f5f8; color: #263448; }
            QWidget#commandBar, QWidget#statusBar, QWidget#dockTitle, QWidget#propertyFooter {
                background: #e8edf3; border-bottom: 1px solid #c9d3df;
            }
            QWidget#folderPanel, QWidget#propertyBody, QWidget#sidePanel { background: #f8fafc; }
            QWidget#folderPanel, QWidget#statusBar { border-top: 1px solid #c9d3df; }
            QWidget#dockTitle QLabel { font-weight: 600; }
            QLabel#treeFooter { color: #526378; padding: 6px 9px; border-top: 1px solid #c9d3df; }
            QLabel#pendingText { color: #8a510b; }
            QFrame#divider { color: #b9c7d6; }
            QPushButton { padding: 4px 8px; min-height: 19px; }
            QPushButton#folderToggle:checked { color: #214e89; background: #dbe8fa; border: 1px solid #a8bfdc; border-radius: 3px; }
            QPushButton#previewAction {
                background: #225bb0; color: white; border: 1px solid #184d98; border-radius: 3px;
            }
            QPushButton#previewAction:hover:enabled { background: #1b4d98; }
            QPushButton#previewAction:focus:enabled { border: 2px solid #133a74; padding: 3px 7px; }
            QPushButton#previewAction:disabled { color: #586a80; background: #dce5f1; border-color: #b9c7d6; }
            QToolButton#propertySection {
                background: #e8edf3; border: 0; border-bottom: 1px solid #c9d3df;
                padding: 6px 8px; text-align: left; font-weight: 600;
            }
            QToolButton#propertySection:focus { border: 1px solid #225bb0; padding: 5px 7px; }
            QTreeWidget, QPlainTextEdit { border: 0; }
            QTreeWidget::item { padding: 4px 2px; }
            QTreeWidget::item:selected, QTreeWidget::item:selected:!active {
                color: #162b48; background: #dbe9fd;
            }
            QSplitter#workArea::handle { background: #c9d3df; width: 4px; }
            QSplitter#viewDivider::handle { background: #708399; width: 3px; }
        """)

    @Slot()
    def choose_input(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "选择包含 STL 文件的输入文件夹")
        if not chosen:
            return
        source = Path(chosen)
        self.input_edit.setText(str(source))
        self.output_edit.setText(str(source.parent / f"{source.name}_simplified"))
        self.refresh_file_count()

    @Slot()
    def choose_output(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "选择输出文件夹（也可直接输入一个新路径）")
        if chosen:
            self.output_edit.setText(chosen)
            self.refresh_file_count()

    @Slot()
    def refresh_file_count(self) -> None:
        if self.busy:
            return
        raw = self.input_edit.text().strip()
        if not raw:
            self.file_count_label.setText("请选择包含 STL 文件的输入文件夹")
            self.populate_part_list(Path(), [], None)
            return
        source = Path(raw)
        if not source.is_dir():
            self.file_count_label.setText("输入文件夹不存在")
            self.populate_part_list(source, [], None)
            return
        output = Path(self.output_edit.text().strip()) if self.output_edit.text().strip() else None
        files = find_stl_files(source, self.recursive_check.isChecked(), output)
        count = len(files)
        scope = "（包含子文件夹）" if self.recursive_check.isChecked() else ""
        self.file_count_label.setText(f"发现 {count} 个 STL 文件{scope}")
        self.populate_part_list(source, files, output)

    def populate_part_list(self, source: Path, files: list[Path], output: Path | None) -> None:
        role = int(Qt.ItemDataRole.UserRole)
        self.preview_token += 1
        self.file_items.clear()
        self.file_tree.clear()
        recursive = self.recursive_check.isChecked()
        for path in files:
            relative = path.relative_to(source)
            key = relative.as_posix()
            destination = None
            if output:
                destination = output / relative if recursive else output / path.name
            status = "已有结果" if destination and destination.is_file() else "等待处理"
            item = QTreeWidgetItem([str(relative), "—", "—", "—", status, "—"])
            item.setData(0, role, str(path))
            item.setData(0, role + 1, str(destination) if destination else "")
            item.setData(0, role + 2, key)
            item.setToolTip(0, str(path))
            self.file_tree.addTopLevelItem(item)
            self.file_items[key] = item
            cached = self.part_options.get((str(path), str(destination)))
            if cached and destination and destination.is_file():
                self.show_part_options(item, cached)
            draft = self.drafts.get(self.draft_key(item))
            if draft:
                self.show_draft(item, draft)
        if self.file_tree.topLevelItemCount():
            self.file_tree.setCurrentItem(self.file_tree.topLevelItem(0))
        else:
            self.before_preview.set_mesh(None, "未找到 STL 文件")
            self.after_preview.set_mesh(None, "未找到 STL 文件")
        self.update_inspection_status()

    @Slot()
    def on_part_selected(self) -> None:
        selected = self.file_tree.selectedItems()
        self.update_selection_actions()
        if not selected:
            return
        role = int(Qt.ItemDataRole.UserRole)
        item = self.file_tree.currentItem() or selected[0]
        source = Path(item.data(0, role))
        output_text = item.data(0, role + 1)
        output = Path(output_text) if output_text else None
        draft = self.drafts.get(self.draft_key(item))
        if draft:
            output = draft.path
        self.after_preview.title = "简化后（预览未应用）" if draft else "简化后（已保存）"
        self.after_preview._heading.setText(self.after_preview.title)
        self.preview_token += 1
        token = self.preview_token
        self.before_preview.set_loading("正在载入原始模型…")
        self.after_preview.set_loading("正在检查简化结果…")
        loader = PreviewLoaderThread(token, source, output, self)
        self.preview_threads.add(loader)
        loader.loaded.connect(self.on_preview_loaded)
        loader.finished.connect(lambda current=loader: self.preview_threads.discard(current))
        loader.finished.connect(loader.deleteLater)
        loader.start()

    @Slot(int, object, object, str, str)
    def on_preview_loaded(
        self,
        token: int,
        before: PreviewData | None,
        after: PreviewData | None,
        before_error: str,
        after_error: str,
    ) -> None:
        if token != self.preview_token:
            return
        self.before_preview.set_mesh(before, before_error or "无法载入原始模型")
        self.after_preview.set_mesh(after, after_error or "尚无简化结果")
        selected = self.file_tree.selectedItems()
        if not selected:
            return
        item = self.file_tree.currentItem() or selected[0]
        if before:
            item.setText(1, f"{before.face_count:,}")
        if after:
            item.setText(2, f"{after.face_count:,}")
        if before and after and before.face_count:
            reduction = (1.0 - after.face_count / before.face_count) * 100.0
            item.setText(3, f"{reduction:.1f}%")
        self.update_inspection_status()

    @Slot(str)
    def on_file_started(self, key: str) -> None:
        item = self.file_items.get(key)
        if item:
            item.setText(4, "预览计算中" if self.preview_only else "处理中")
            item.setForeground(4, QBrush(QColor("#2f75c8")))

    @Slot(str, int, int, str, str)
    def on_file_result(self, key: str, before: int, after: int, status: str, destination: str) -> None:
        role = int(Qt.ItemDataRole.UserRole)
        item = self.file_items.get(key)
        if not item:
            return
        if self.preview_only:
            if status == "完成" and self.active_options:
                draft = DraftResult(Path(destination), self.active_options, before, after,
                                    self.active_signatures[key])
                self.drafts[self.draft_key(item)] = draft
                self.show_draft(item, draft)
            else:
                item.setText(4, "预览" + status)
                item.setToolTip(4, status)
            if self.file_tree.currentItem() is item:
                self.on_part_selected()
            else:
                self.update_inspection_status()
            return
        if before:
            item.setText(1, f"{before:,}")
        if after:
            item.setText(2, f"{after:,}")
        if before and after:
            item.setText(3, f"{(1.0 - after / before) * 100.0:.1f}%")
        item.setText(4, status)
        item.setData(0, role + 1, destination)
        if status == "完成":
            self.drafts.pop(self.draft_key(item), None)
            item.setForeground(4, QBrush(QColor("#198754")))
            if self.active_options:
                self.part_options[(item.data(0, role), destination)] = self.active_options
                self.show_part_options(item, self.active_options)
        elif status == "已跳过":
            item.setForeground(4, QBrush(QColor("#8a6d1d")))
        else:
            item.setForeground(4, QBrush(QColor("#c23b3b")))
            item.setToolTip(4, status)
        selected = self.file_tree.selectedItems()
        if selected and self.file_tree.currentItem() is item:
            self.on_part_selected()
        else:
            self.update_inspection_status()

    def update_selection_actions(self) -> None:
        selected = self.file_tree.selectedItems()
        idle = self.thread is None and not self.busy
        self.selected_button.setText(f"重做选中（{len(selected)}）")
        self.selected_button.setEnabled(idle and bool(selected))
        role = int(Qt.ItemDataRole.UserRole)
        self.load_part_options_button.setEnabled(
            idle and len(selected) == 1 and
            ((selected[0].data(0, role), selected[0].data(0, role + 1)) in self.part_options
             or self.draft_key(selected[0]) in self.drafts)
        )
        self.preview_selected_button.setEnabled(idle and bool(selected))
        has_draft = any(self.draft_key(item) in self.drafts for item in selected)
        self.apply_preview_button.setEnabled(idle and has_draft)
        self.discard_preview_button.setEnabled(idle and has_draft)
        self.update_inspection_status()

    def update_inspection_status(self) -> None:
        selected = self.file_tree.selectedItems()
        current = (self.file_tree.currentItem() or selected[0]) if selected else None
        self.selection_label.setText(f"选中 {len(selected)} 件")
        pending = sum(self.draft_key(item) in self.drafts for item in self.file_items.values()) if self.drafts else 0
        self.draft_count_label.setText(f"待应用 {pending} 件")
        self.current_part_label.setText(current.text(0) if current else "未选择零件")
        self.current_part_label.setToolTip(current.toolTip(0) if current else "")
        for column, label in enumerate(self.part_stat_labels, 1):
            label.setText(current.text(column) if current else "—")

    def draft_key(self, item: QTreeWidgetItem) -> tuple[str, str]:
        role = int(Qt.ItemDataRole.UserRole)
        return (str(Path(item.data(0, role)).resolve()),
                str(Path(item.data(0, role + 1)).resolve()))

    def show_draft(self, item: QTreeWidgetItem, draft: DraftResult) -> None:
        item.setText(1, f"{draft.before:,}")
        item.setText(2, f"{draft.after:,}")
        item.setText(3, f"{(1 - draft.after / draft.before) * 100:.1f}%")
        item.setText(4, "预览待应用")
        item.setForeground(4, QBrush(QColor("#9b6500")))
        self.show_part_options(item, draft.options)

    @Slot()
    def apply_selected_previews(self) -> None:
        if self.thread is not None:
            return
        role = int(Qt.ItemDataRole.UserRole)
        count = 0
        for item in self.file_tree.selectedItems():
            key = self.draft_key(item)
            draft = self.drafts.get(key)
            if draft is None:
                continue
            temporary = None
            try:
                source = Path(key[0])
                destination = Path(key[1])
                stat = source.stat()
                if (stat.st_size, stat.st_mtime_ns) != draft.source_signature:
                    raise ValueError("原始 STL 已变化，请重新预览")
                if source == destination:
                    raise ValueError("输出文件不能覆盖原始 STL")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(prefix=".stl_apply_", suffix=".stl",
                                                  dir=destination.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                shutil.copyfile(draft.path, temporary)
                os.replace(temporary, destination)
                self.part_options[(item.data(0, role), item.data(0, role + 1))] = draft.options
                self.drafts.pop(key)
                item.setText(4, "完成")
                item.setForeground(4, QBrush(QColor("#198754")))
                self.append_log(f"[应用预览] {item.text(0)}：保存 {draft.after:,} 面")
                count += 1
                self.last_output = Path(self.output_edit.text().strip()).resolve()
                self.open_output_button.setEnabled(True)
            except Exception as exc:
                item.setText(4, "应用失败（预览保留）")
                item.setToolTip(4, str(exc))
                self.append_log(f"[应用失败] {item.text(0)}：{exc}")
            finally:
                if temporary and temporary.exists():
                    temporary.unlink()
        self.progress_label.setText(f"已应用 {count} 个零件的预览结果")
        self.on_part_selected()

    @Slot()
    def discard_selected_previews(self) -> None:
        if self.thread is not None:
            return
        role = int(Qt.ItemDataRole.UserRole)
        for item in self.file_tree.selectedItems():
            if self.drafts.pop(self.draft_key(item), None) is None:
                continue
            path = Path(item.data(0, role + 1))
            item.setText(4, "已有结果" if path.is_file() else "等待处理")
            item.setForeground(4, QBrush(QColor("#5d6673")))
            item.setText(2, "—")
            item.setText(3, "—")
            item.setText(5, "—")
            item.setToolTip(5, "")
            options = self.part_options.get((item.data(0, role), item.data(0, role + 1)))
            if options:
                self.show_part_options(item, options)
        self.on_part_selected()

    def show_part_options(self, item: QTreeWidgetItem, options: SimplifyOptions) -> None:
        target = (f"保留 {options.retain_percent:g}%" if options.target_mode == "percent"
                  else f"目标 {options.target_faces:,} 面")
        item.setText(5, target)
        details = [target, f"质量阈值：{options.quality_threshold:g}",
                   f"边界权重：{options.boundary_weight:g}", f"平面权重：{options.planar_weight:g}"]
        for label, enabled in (("保留边界", options.preserve_boundary),
                               ("保持法线", options.preserve_normal),
                               ("保持拓扑", options.preserve_topology),
                               ("最优位置", options.optimal_placement),
                               ("平面简化", options.planar_simplification),
                               ("质量加权", options.weighted_simplification),
                               ("自动清理", options.post_cleaning)):
            details.append(f"{label}：{'开启' if enabled else '关闭'}")
        item.setToolTip(5, "\n".join(details))

    @Slot()
    def load_part_options(self) -> None:
        selected = self.file_tree.selectedItems()
        if len(selected) != 1 or self.thread is not None:
            return
        role = int(Qt.ItemDataRole.UserRole)
        options = self.part_options.get((selected[0].data(0, role), selected[0].data(0, role + 1)))
        draft = self.drafts.get(self.draft_key(selected[0]))
        if draft:
            options = draft.options
        if not options:
            return
        self.faces_radio.setChecked(options.target_mode == "faces")
        self.percent_radio.setChecked(options.target_mode == "percent")
        self.target_faces_spin.setValue(options.target_faces)
        self.retain_spin.setValue(options.retain_percent)
        self.quality_spin.setValue(options.quality_threshold)
        self.boundary_weight_spin.setValue(options.boundary_weight)
        self.planar_weight_spin.setValue(options.planar_weight)
        for control, value in ((self.preserve_boundary_check, options.preserve_boundary),
                               (self.preserve_normal_check, options.preserve_normal),
                               (self.preserve_topology_check, options.preserve_topology),
                               (self.optimal_check, options.optimal_placement),
                               (self.planar_check, options.planar_simplification),
                               (self.weighted_check, options.weighted_simplification),
                               (self.clean_check, options.post_cleaning)):
            control.setChecked(value)
        self.update_target_state()

    @Slot()
    def update_target_state(self) -> None:
        use_faces = self.faces_radio.isChecked()
        self.target_faces_spin.setEnabled(use_faces)
        self.retain_spin.setEnabled(not use_faces)

    @Slot()
    def restore_defaults(self) -> None:
        if self.thread and self.thread.isRunning():
            return
        self.percent_radio.setChecked(True)
        self.target_faces_spin.setValue(1000)
        self.retain_spin.setValue(10)
        self.quality_spin.setValue(0.3)
        self.preserve_boundary_check.setChecked(True)
        self.boundary_weight_spin.setValue(1)
        self.preserve_normal_check.setChecked(True)
        self.preserve_topology_check.setChecked(True)
        self.optimal_check.setChecked(True)
        self.planar_check.setChecked(True)
        self.planar_weight_spin.setValue(0.001)
        self.weighted_check.setChecked(False)
        self.clean_check.setChecked(True)
        self.update_target_state()

    def current_options(self) -> SimplifyOptions:
        return SimplifyOptions(
            target_mode="faces" if self.faces_radio.isChecked() else "percent",
            target_faces=self.target_faces_spin.value(),
            retain_percent=self.retain_spin.value(),
            quality_threshold=self.quality_spin.value(),
            preserve_boundary=self.preserve_boundary_check.isChecked(),
            boundary_weight=self.boundary_weight_spin.value(),
            preserve_normal=self.preserve_normal_check.isChecked(),
            preserve_topology=self.preserve_topology_check.isChecked(),
            optimal_placement=self.optimal_check.isChecked(),
            planar_simplification=self.planar_check.isChecked(),
            planar_weight=self.planar_weight_spin.value(),
            weighted_simplification=self.weighted_check.isChecked(),
            post_cleaning=self.clean_check.isChecked(),
        )

    @Slot()
    def start_batch(self) -> None:
        self.begin_processing(False)

    @Slot()
    def start_selected(self) -> None:
        self.begin_processing(True)

    @Slot()
    def start_preview(self) -> None:
        self.begin_processing(True, preview_only=True)

    def begin_processing(self, selected_only: bool, preview_only: bool = False) -> None:
        if self.thread is not None:
            return
        try:
            if not self.input_edit.text().strip() or not self.output_edit.text().strip():
                raise ValueError("请选择输入和输出文件夹")
            source = Path(self.input_edit.text().strip()).resolve()
            output = Path(self.output_edit.text().strip()).resolve()
            if not source.is_dir():
                raise ValueError("请选择有效的输入文件夹")
            if source == output:
                raise ValueError("输出文件夹不能与输入文件夹相同，以免覆盖原始文件")
            files = find_stl_files(source, self.recursive_check.isChecked(), output)
            if selected_only:
                role = int(Qt.ItemDataRole.UserRole)
                selected_paths = {Path(item.data(0, role)).resolve()
                                  for item in self.file_tree.selectedItems()}
                if not selected_paths:
                    raise ValueError("请先在列表中选中一个或多个零件（Ctrl / Shift 多选）")
                available = {path.resolve() for path in files}
                if not selected_paths.issubset(available):
                    raise ValueError("文件夹或零件已变化，请刷新文件夹后重新选择")
                files = [path for path in files if path.resolve() in selected_paths]
            if not files:
                raise ValueError("输入文件夹中没有找到 STL 文件")
            options = self.current_options()
        except Exception as exc:
            QMessageBox.critical(self, "无法开始处理", str(exc))
            return

        try:
            if preview_only:
                directory = tempfile.TemporaryDirectory(prefix="stl_preview_")
                self.draft_directories.append(directory)
                worker_output = Path(directory.name)
            else:
                output.mkdir(parents=True, exist_ok=True)
                worker_output = output
        except OSError as exc:
            QMessageBox.critical(self, "无法创建输出文件夹", str(exc))
            return
        if not preview_only:
            self.last_output = output
        self.preview_only = preview_only
        self.active_source_root = source
        self.active_output_root = output
        self.active_signatures = {}
        for path in files:
            stat = path.stat()
            self.active_signatures[path.relative_to(source).as_posix()] = (stat.st_size, stat.st_mtime_ns)
        self.active_options = options
        if not selected_only:
            self.populate_part_list(source, files, output)
        self.open_output_button.setEnabled(False)
        if not selected_only:
            self.log_edit.clear()
        elif preview_only:
            self.append_log("预览选中零件：临时计算，不修改输出文件")
        else:
            self.append_log("重新处理选中零件：从原始 STL 计算，覆盖对应输出")
        self.append_log(f"输入：{source}")
        self.append_log(f"输出：{output}")
        self.append_log(f"共 {len(files)} 个 STL 文件")
        self.progress.setRange(0, len(files))
        self.progress.setValue(0)
        self.progress_label.setText(f"准备处理 {len(files)} 个文件…")
        self.set_running(True)

        self.thread = QThread(self)
        self.worker = BatchWorker(
            source,
            worker_output,
            files,
            options,
            selected_only or self.overwrite_check.isChecked(),
            self.recursive_check.isChecked(),
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.status.connect(self.on_status)
        self.worker.progress.connect(self.on_progress)
        self.worker.log.connect(self.append_log)
        self.worker.file_started.connect(self.on_file_started)
        self.worker.file_result.connect(self.on_file_result)
        self.worker.completed.connect(self.on_completed)
        self.worker.cancelled.connect(self.on_cancelled)
        self.worker.completed.connect(self.thread.quit)
        self.worker.cancelled.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.on_thread_finished)
        self.cancel_signal.connect(self.worker.request_cancel)
        self.thread.start()

    @Slot()
    def cancel_batch(self) -> None:
        if self.thread and self.thread.isRunning():
            # Direct assignment is deliberate: the worker's event loop is busy during a mesh operation,
            # so a queued slot would not run until the entire batch had finished.
            if self.worker:
                self.worker.cancel_requested = True
            self.cancel_button.setEnabled(False)
            self.progress_label.setText("将在当前文件处理完成后取消…")

    @Slot(int, int, str)
    def on_status(self, done: int, total: int, text: str) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.progress_label.setText(f"{done}/{total}  {text}")

    @Slot(int, int)
    def on_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(done)

    @Slot(str)
    def append_log(self, text: str) -> None:
        self.log_edit.appendPlainText(text)

    @Slot(int, int, int, int, str)
    def on_completed(self, ok: int, skipped: int, failed: int, total: int, output: str) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(total)
        if self.preview_only:
            self.progress_label.setText(f"预览完成：成功 {ok}，失败 {failed}。满意后点击“应用所选预览”保存。")
            self.set_running(False)
            self.open_output_button.setEnabled(bool(self.last_output))
            return
        self.progress_label.setText(f"处理完成：成功 {ok}，跳过 {skipped}，失败 {failed}")
        self.set_running(False)
        self.open_output_button.setEnabled(True)
        QMessageBox.information(
            self,
            "批量处理完成",
            f"成功：{ok}\n跳过：{skipped}\n失败：{failed}\n\n输出文件夹：\n{output}",
        )

    @Slot(int, int, int, int)
    def on_cancelled(self, ok: int, skipped: int, failed: int, total: int) -> None:
        self.progress_label.setText(f"已取消：成功 {ok}，跳过 {skipped}，失败 {failed}，共 {total}")
        self.append_log("[取消] 用户取消了剩余任务")
        self.set_running(False)
        self.open_output_button.setEnabled(bool(self.last_output))

    @Slot()
    def on_thread_finished(self) -> None:
        self.worker = None
        if self.thread:
            self.thread.deleteLater()
        self.thread = None
        self.set_running(False)

    def set_running(self, running: bool) -> None:
        idle = not running and self.thread is None
        self.busy = not idle
        self.start_button.setEnabled(idle)
        self.cancel_button.setEnabled(running)
        self.folders_group.setEnabled(idle)
        self.settings_group.setEnabled(idle)
        self.selected_button.setEnabled(idle and bool(self.file_tree.selectedItems()))
        self.load_part_options_button.setEnabled(False)
        self.preview_selected_button.setEnabled(False)
        self.apply_preview_button.setEnabled(False)
        self.discard_preview_button.setEnabled(False)
        if idle:
            self.update_selection_actions()

    @Slot()
    def open_output_folder(self) -> None:
        if self.last_output and self.last_output.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_output)))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.thread and self.thread.isRunning():
            answer = QMessageBox.question(
                self,
                "正在处理",
                "当前任务仍在运行。确定要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            if self.worker:
                self.worker.cancel_requested = True
            self.thread.quit()
            self.thread.wait(3000)
        for preview_thread in list(self.preview_threads):
            preview_thread.wait(1500)
        if self.thread is None or not self.thread.isRunning():
            for directory in self.draft_directories:
                directory.cleanup()
        event.accept()


def self_test() -> int:
    try:
        import numpy as np

        pymeshlab = import_meshlab()
        vertices = np.array(
            [
                [-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
                [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1],
            ],
            dtype=np.float64,
        )
        faces = np.array(
            [
                [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
                [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
                [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7],
            ],
            dtype=np.int32,
        )
        mesh_set = pymeshlab.MeshSet()
        mesh_set.add_mesh(pymeshlab.Mesh(vertex_matrix=vertices, face_matrix=faces), "cube")
        mesh_set.apply_filter(
            "meshing_decimation_quadric_edge_collapse",
            targetfacenum=8,
            preservenormal=True,
            optimalplacement=True,
            autoclean=True,
        )
        count = int(mesh_set.current_mesh().face_number())
        if not 0 < count <= 8:
            return 2
        with tempfile.TemporaryDirectory(prefix="stl_batch_selftest_") as temp_dir:
            output = Path(temp_dir) / "中文输出" / "测试模型.stl"
            save_binary_stl_unicode_safe(mesh_set.current_mesh(), output)
            check = pymeshlab.MeshSet()
            check.load_new_mesh(str(output))
            if int(check.current_mesh().face_number()) != count:
                return 3
            if load_stl_preview(output).face_count != count:
                return 4
        return 0
    except Exception:
        traceback.print_exc()
        return 1


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    if "--version" in sys.argv:
        print(f"{APP_NAME} {APP_VERSION}")
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    window = MainWindow()
    if "--preview-check" in sys.argv:
        import json
        import time

        check_index = sys.argv.index("--preview-check")
        sample = Path(sys.argv[check_index + 1])
        report = Path(sys.argv[check_index + 2])
        data = load_stl_preview(sample)
        window.before_preview.set_mesh(data)
        window.after_preview.set_mesh(data)
        window.show()
        for _ in range(12):
            app.processEvents()
            time.sleep(0.02)
        results = []
        for preview in (window.before_preview, window.after_preview):
            if not preview.isValid():
                return 5
            frame = preview.grabFramebuffer()
            preview.makeCurrent()
            error = preview._gl.glGetError()
            preview.doneCurrent()
            if error or frame.isNull() or preview._vertices is None:
                return 6
            results.append(dict(renderer=preview.renderer, faces=preview._face_count,
                                drawn_vertices=len(preview._vertices),
                                gpu_buffers=preview._buffers is not None))
        report.write_text(json.dumps(results), encoding="utf-8")
        window.grab().save(str(report.with_suffix(".png")))
        window.close()
        app.processEvents()
        return 0
    if "--gui-smoke-test" in sys.argv:
        window.show()
        app.processEvents()
        window.close()
        return 0
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
