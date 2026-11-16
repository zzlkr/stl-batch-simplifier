import json
import time
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest
from PySide6.QtCore import QPoint, Qt

from stl_batch_simplifier_qt import MainWindow, load_stl_preview

from fixtures import test_run_dir, write_sphere

root = test_run_dir('gl')
app = QApplication([])
print('app', flush=True)
window = MainWindow()
source = root / 'input'
source.mkdir(exist_ok=True)
sample = source / 'sphere.stl'
write_sphere(sample, subdivisions=6)
loaded = load_stl_preview(sample)
assert len(loaded.triangles) == loaded.face_count == 81920
window.input_edit.setText(str(source))
window.output_edit.setText(str(root / 'output'))
window.refresh_file_count()
window.show()
QMessageBox.information = lambda *args, **kwargs: QMessageBox.StandardButton.Ok
window.overwrite_check.setChecked(True)
window.start_batch()
print('batch started', flush=True)
deadline = time.perf_counter() + 20
while (window.thread is not None or window.preview_threads or not window.before_preview.isValid()) and time.perf_counter() < deadline:
    app.processEvents()
    QTest.qWait(10)
app.processEvents()
print('batch loop ended', flush=True)
preview = window.before_preview
assert preview.isValid(), 'No OpenGL context'
assert preview._vertices is not None
assert len(preview._vertices) == 81920 * 3
assert preview._buffer_functions is not None, 'GPU vertex buffers unavailable'
assert window.after_preview._vertices is not None
assert window.after_preview._face_count < preview._face_count
preview.makeCurrent()
error = preview._gl.glGetError()
preview.doneCurrent()
assert error == 0, f'OpenGL error: {error}'

# Verify a solid sphere has no sampled-away holes in the central projected area.
image = preview.grabFramebuffer()
print('framebuffer grabbed', flush=True)
background = image.pixelColor(2, image.height() // 2)
center = (image.width() // 2, image.height() // 2)
radius = int(min(image.width(), image.height()) * 0.24)
hole_count = 0
tested = 0
for y in range(center[1] - radius, center[1] + radius, 5):
    for x in range(center[0] - radius, center[0] + radius, 5):
        if (x-center[0])**2 + (y-center[1])**2 > radius**2:
            continue
        color = image.pixelColor(x, y)
        tested += 1
        if abs(color.red()-background.red()) + abs(color.green()-background.green()) + abs(color.blue()-background.blue()) < 12:
            hole_count += 1
assert hole_count == 0, f'Visible holes: {hole_count}/{tested}'

# Exercise actual mouse interaction and synchronized camera updates.
QTest.mousePress(preview, Qt.MouseButton.LeftButton, pos=QPoint(100, 100))
QTest.mouseMove(preview, QPoint(180, 130), delay=10)
QTest.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=QPoint(180, 130))
print('mouse done', flush=True)
app.processEvents()
assert window.before_preview._yaw == window.after_preview._yaw
times = []
for index in range(40):
    start = time.perf_counter()
    preview.set_view(-35 + index * 2, 24, 1)
    window.after_preview.set_view(-35 + index * 2, 24, 1)
    preview.grabFramebuffer()
    window.after_preview.grabFramebuffer()
    app.processEvents()
    times.append(time.perf_counter() - start)
window.grab().save(str(root / 'preview_gl.png'))
result = dict(renderer=preview.renderer, faces=loaded.face_count,
              simplified_faces=window.after_preview._face_count,
              holes=hole_count, gpu_buffers=bool(preview._buffers),
              average_frame_ms=round(sum(times[5:]) / len(times[5:]) * 1000, 2))
print(json.dumps(result))
(root / 'preview_gl_results.json').write_text(json.dumps(result), encoding='utf-8')
window.close()
app.processEvents()
