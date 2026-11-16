import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton, QSplitter

from stl_batch_simplifier_qt import MainWindow

from fixtures import test_run_dir, write_sphere

root = test_run_dir("layout")
source, output = root / "input", root / "output"
source.mkdir()
output.mkdir()
write_sphere(source / "sphere.stl")
write_sphere(output / "sphere.stl", subdivisions=2)
app = QApplication([])
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
advanced = next(b for b in window.findChildren(QToolButton) if b.text() == "高级参数")
assert not window.planar_weight_spin.isVisible()
advanced.click()
assert window.planar_weight_spin.isVisible()
advanced.click()
assert not window.planar_weight_spin.isVisible()
folders = window.findChild(QPushButton, "folderToggle")
height = window.before_preview.height()
folders.click()
settle()
assert not window.folders_group.isVisible()
assert window.before_preview.height() > height
area = window.findChild(QSplitter, "workArea")
before_sizes = area.sizes()
area.moveSplitter(before_sizes[0] + 30, 1)
assert area.sizes()[0] > before_sizes[0]
window.resize(960, 560)
settle()
assert window.width() == 960 and window.height() == 560, window.size()
assert window.before_preview.width() >= 244 and window.after_preview.width() >= 244
assert window.retain_spin.width() > 45 and window.preview_selected_button.isVisible()
assert window.part_stat_labels[0].text() != "—"
assert window.before_preview.grabFramebuffer().width() > 0
window.resize(1380, 800)
area.setSizes([236, 885, 249])
settle()
window.grab().save(str(root / "workbench.png"))
window.close()
settle()
print("Workbench layout: 960×560, splitter, folders, advanced, detailed columns, counts and real GL preview passed.")
