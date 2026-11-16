import hashlib
import json
import os
import shutil
import tempfile
import time

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QItemSelectionModel
from stl_batch_simplifier_qt import MainWindow, load_stl_preview

from fixtures import test_run_dir, write_sphere

base = test_run_dir('draft')
source, output = base / '原始', base / '输出'
source.mkdir(parents=True)
sample = base / 'sphere.stl'
write_sphere(sample)
tempfile.tempdir = str(base)
for name in ('零件A.STL', '零件B.stl', '子目录/零件C.STL'):
    destination = source / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sample, destination)
app = QApplication([])
QMessageBox.information = lambda *args: QMessageBox.StandardButton.Ok
QMessageBox.critical = lambda *args: (_ for _ in ()).throw(RuntimeError(str(args[-1])))
window = MainWindow()
window.input_edit.setText(str(source))
window.output_edit.setText(str(output))
window.recursive_check.setChecked(True)
window.refresh_file_count()
window.show()
for _ in range(10):
    app.processEvents()
    time.sleep(0.02)

def wait():
    deadline = time.perf_counter() + 20
    while (window.thread is not None or window.preview_threads) and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert window.thread is None and not window.preview_threads
    app.processEvents()

def select(keys):
    window.file_tree.clearSelection()
    for key in keys:
        window.file_items[key].setSelected(True)
    window.file_tree.setCurrentItem(window.file_items[keys[0]], 0, QItemSelectionModel.SelectionFlag.NoUpdate)
    app.processEvents()

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

select(['零件A.STL', '子目录/零件C.STL'])
window.start_preview()
wait()
assert not output.exists(), 'Preview created formal output'
assert len(window.drafts) == 2
assert all(draft.after == 128 for draft in window.drafts.values())
assert window.after_preview._face_count == 128
window.retain_spin.setValue(50)
window.start_preview()
wait()
assert not output.exists()
assert all(draft.after == 640 for draft in window.drafts.values())
select(['零件A.STL'])
# Applying saves the already shown result, even if controls were edited afterward.
window.retain_spin.setValue(5)
window.apply_selected_previews()
wait()
assert load_stl_preview(output / '零件A.STL').face_count == 640
assert not (output / '子目录/零件C.STL').exists()
select(['子目录/零件C.STL'])
window.discard_selected_previews()
wait()
assert not window.drafts
assert not (output / '子目录/零件C.STL').exists()

window.retain_spin.setValue(10)
window.overwrite_check.setChecked(True)
window.start_batch()
wait()
saved = {p.relative_to(output).as_posix(): digest(p) for p in output.rglob('*.stl')}
saved['零件A.STL'] = digest(output / '零件A.STL')
saved['子目录/零件C.STL'] = digest(output / '子目录/零件C.STL')
select(['零件A.STL', '子目录/零件C.STL'])
window.retain_spin.setValue(25)
window.start_preview()
wait()
for key, value in saved.items():
    assert digest(output / key) == value, 'Preview overwrote a saved file'
select(['子目录/零件C.STL'])
window.apply_selected_previews()
wait()
assert load_stl_preview(output / '子目录/零件C.STL').face_count == 320
assert digest(output / '零件A.STL') == saved['零件A.STL']
select(['零件A.STL'])
window.discard_selected_previews()
wait()
assert window.after_preview._face_count == 128
assert not window.drafts

window.retain_spin.setValue(50)
window.start_preview()
wait()
assert window.after_preview._face_count == 640
window.grab().save(str(base / 'draft_preview.png'))
stat = (source / '零件A.STL').stat()
os.utime(source / '零件A.STL', ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
window.apply_selected_previews()
wait()
assert window.drafts
assert digest(output / '零件A.STL') == saved['零件A.STL']
window.close()
app.processEvents()
assert not list(base.glob('stl_preview_*')), 'Preview cache not cleaned on close'
print(json.dumps(dict(result='PASS', preview_leaves_outputs_unchanged=True,
                      repeated_preview_from_original=True, apply_cached_result=True,
                      multi_select=True, discard_restores_saved=True,
                      changed_source_detected=True, cache_cleanup=True)))
