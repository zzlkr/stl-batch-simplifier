import hashlib
import json
import shutil
import time

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QItemSelectionModel

from stl_batch_simplifier_qt import MainWindow, load_stl_preview

from fixtures import test_run_dir, write_sphere

test_dir = test_run_dir('selected')
source, output = test_dir / '原始', test_dir / '输出'
source.mkdir(parents=True)
sample = test_dir / 'sphere.stl'
write_sphere(sample)
for name in ('零件A.STL', '零件B.stl', '子目录/零件C.STL'):
    destination = source / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sample, destination)

app = QApplication([])
QMessageBox.information = lambda *args: QMessageBox.StandardButton.Ok
def critical(*args):
    raise RuntimeError(str(args[-1]))
QMessageBox.critical = critical
window = MainWindow()
window.input_edit.setText(str(source))
window.output_edit.setText(str(output))
window.recursive_check.setChecked(True)
window.refresh_file_count()
window.show()

def wait_done():
    deadline = time.perf_counter() + 20
    while (window.thread is not None or window.preview_threads) and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert window.thread is None
    assert not window.preview_threads
    app.processEvents()

def hashes():
    return {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in output.rglob('*') if p.is_file()}

def select(keys):
    window.file_tree.clearSelection()
    for key in keys:
        item = window.file_items[key]
        item.setSelected(True)
    window.file_tree.setCurrentItem(window.file_items[keys[0]], 0,
                                    QItemSelectionModel.SelectionFlag.NoUpdate)
    app.processEvents()
    assert len(window.file_tree.selectedItems()) == len(keys)

window.start_batch()
wait_done()
original_hashes = hashes()
assert len(original_hashes) == 3
assert all(load_stl_preview(output / p).face_count == 128 for p in original_hashes)
select(['零件A.STL'])
window.retain_spin.setValue(50)
window.start_selected()
wait_done()
after_single = hashes()
assert load_stl_preview(output / '零件A.STL').face_count == 640
assert after_single['零件B.stl'] == original_hashes['零件B.stl']
assert after_single['子目录/零件C.STL'] == original_hashes['子目录/零件C.STL']
assert window.file_tree.topLevelItemCount() == 3
assert len(window.file_tree.selectedItems()) == 1

select(['零件A.STL', '子目录/零件C.STL'])
window.retain_spin.setValue(25)
assert not window.overwrite_check.isChecked()
window.start_selected()
wait_done()
assert load_stl_preview(output / '零件A.STL').face_count == 320
assert load_stl_preview(output / '子目录/零件C.STL').face_count == 320
assert hashes()['零件B.stl'] == original_hashes['零件B.stl']
assert len(window.file_tree.selectedItems()) == 2
select(['零件B.stl'])
window.load_part_options()
assert window.retain_spin.value() == 10
select(['零件A.STL'])
window.load_part_options()
assert window.retain_spin.value() == 25
wait_done()
window.grab().save(str(test_dir / 'selected_parts.png'))
window.close()
app.processEvents()
print(json.dumps(dict(result='PASS', single_from_original=640, multiple_from_original=320,
                     unselected_unchanged=True, parameter_reload=True)))
