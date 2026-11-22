import time

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton, QToolButton, QSplitter

from stl_batch_simplifier_qt import MainWindow

from fixtures import test_run_dir, write_sphere

root = test_run_dir("layout")
source, output = root / "input", root / "output"
source.mkdir()
output.mkdir()
write_sphere(source / "sphere.stl")
write_sphere(output / "sphere.stl", subdivisions=2)
app = QApplication([])
app.setFont(QFont("Microsoft YaHei UI", 10))
window = MainWindow()
window.show()
window.input_edit.setText(str(source))
window.output_edit.setText(str(output))
window.refresh_file_count()

def settle():
    deadline = time.monotonic() + 8
    while window.preview_threads and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    app.processEvents()

settle()
assert window.before_preview.isValid() and window.after_preview.isValid()
assert window.before_preview._face_count == 1280
assert window.after_preview._face_count == 320
assert window.file_tree.isColumnHidden(1)
details = next(b for b in window.findChildren(QToolButton) if b.text() == "详细列")
details.click()
assert all(not window.file_tree.isColumnHidden(i) for i in range(6))
details.click()
assert window.file_tree.isColumnHidden(1)
options = window.current_options()
assert (options.target_mode, options.target_faces, options.retain_percent) == ("percent", 1000, 10.0)
assert (options.quality_threshold, options.boundary_weight, options.planar_weight) == (0.3, 1.0, 0.001)
assert options.preserve_boundary and options.preserve_normal and options.preserve_topology
assert options.optimal_placement and options.planar_simplification and options.post_cleaning
assert not options.weighted_simplification
assert window.faces_radio.text() == "指定目标面数"
assert window.percent_radio.text() == "指定保留比例"
assert window.optimal_check.text() == "简化顶点采用最优位置"
assert window.weighted_check.text() == "按三角面质量加权简化"
selected_faces = window.findChild(QCheckBox, "selectedFaces")
assert selected_faces is not None and not selected_faces.isEnabled()
assert not window.target_faces_spin.isEnabled() and window.retain_spin.isEnabled()
window.faces_radio.click()
assert window.target_faces_spin.isEnabled() and not window.retain_spin.isEnabled()
defaults = next(b for b in window.findChildren(QPushButton) if b.text() == "恢复默认参数")
defaults.click()
assert window.current_options() == options
folders = window.findChild(QPushButton, "folderToggle")
height = window.before_preview.height()
folders.click()
settle()
assert not window.folders_group.isVisible()
assert window.before_preview.height() > height
area = window.findChild(QSplitter, "workArea")
assert area.count() == 2
before_sizes = area.sizes()
area.moveSplitter(before_sizes[0] + 30, 1)
assert area.sizes()[0] > before_sizes[0]
window.resize(960, 560)
folders.click()
settle()
assert window.width() == 960 and window.height() == 560, window.size()
assert window.before_preview.width() >= 244 and window.after_preview.width() >= 244
assert window.before_preview.height() >= 140 and window.after_preview.height() >= 140
assert window.settings_group.geometry().top() > area.geometry().bottom()
assert window.settings_group.width() == window.centralWidget().width()
for control in (
    window.faces_radio, window.target_faces_spin, window.percent_radio, window.retain_spin,
    window.quality_spin, window.preserve_boundary_check, window.boundary_weight_spin,
    window.preserve_normal_check, window.preserve_topology_check, window.optimal_check,
    window.planar_check, window.planar_weight_spin, window.weighted_check,
    window.clean_check, selected_faces, window.load_part_options_button, defaults,
):
    assert window.settings_group.isAncestorOf(control)
    assert control.visibleRegion().boundingRect() == control.rect(), control
assert window.preview_selected_button.isVisible()
assert window.part_stat_labels[0].text() != "—"
assert window.before_preview.grabFramebuffer().width() > 0
window.resize(1380, 800)
area.setSizes([260, 1116])
folders.click()
settle()
window.grab().save(str(root / "workbench.png"))
window.close()
settle()
print(f"Workbench layout: 960×560, all settings visible, v1.6 defaults and live GL preview passed.\n{root}")
