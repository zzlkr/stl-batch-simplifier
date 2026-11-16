"""Opaque full-mesh OpenGL preview, using Windows' built-in OpenGL interface."""
from __future__ import annotations

import ctypes
import math

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QLabel


class MeshPreviewWidget(QOpenGLWidget):
    view_changed = Signal(float, float, float)

    def __init__(self, title, accent, parent=None):
        super().__init__(parent)
        fmt = QSurfaceFormat()
        fmt.setVersion(2, 1)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
        fmt.setDepthBufferSize(24)
        fmt.setSamples(4)
        self.setFormat(fmt)
        self.title = title
        self.accent = QColor(accent)
        self._triangles = None
        self._vertices = None
        self._normals = None
        self._face_count = 0
        self._message = "选择左侧零件以载入预览"
        self._yaw, self._pitch, self._zoom = -35.0, 24.0, 1.0
        self._last_pos = None
        self._gl = None
        self._buffer_functions = None
        self._buffers = None
        self._upload_pending = False
        self.setMinimumSize(320, 260)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._heading = QLabel(title, self)
        self._info = QLabel(self)
        self._status = QLabel(self._message, self)
        self._footer = QLabel("拖拽旋转 · 滚轮缩放 · 双击复位", self)
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for label in (self._heading, self._info, self._status, self._footer):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            label.setStyleSheet("color: #cbd2de; background: transparent; font-size: 12px;")
        self._heading.setStyleSheet("color: #ffffff; background: transparent; font-size: 14px;")

    def set_mesh(self, data, message=""):
        if data is None:
            self._triangles = self._vertices = self._normals = None
            self._face_count = 0
            self._message = message or "暂无预览"
        else:
            triangles = np.asarray(data.triangles, dtype=np.float32)
            points = triangles.reshape(-1, 3)
            low, high = points.min(axis=0), points.max(axis=0)
            span = float(np.max(high - low))
            if not math.isfinite(span) or span <= 1e-20:
                span = 1.0
            self._triangles = (triangles - (low + high) * 0.5) / span
            self._vertices = np.ascontiguousarray(self._triangles.reshape(-1, 3), dtype=np.float32)
            normals = np.cross(self._triangles[:, 1] - self._triangles[:, 0],
                               self._triangles[:, 2] - self._triangles[:, 0])
            lengths = np.linalg.norm(normals, axis=1)
            valid = lengths > 1e-20
            normals[valid] /= lengths[valid, None]
            normals[~valid] = (0, 0, 1)
            self._normals = np.ascontiguousarray(np.repeat(normals, 3, axis=0), dtype=np.float32)
            self._face_count = data.face_count
            self._message = ""
            self._upload_pending = True
        self._info.setText(f"{self._face_count:,} 个三角面" if self._face_count else "")
        self._status.setText(self._message)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._heading.setGeometry(14, 8, self.width() - 28, 24)
        self._info.setGeometry(14, 32, self.width() - 28, 24)
        self._status.setGeometry(10, 60, self.width() - 20, max(30, self.height() - 90))
        self._footer.setGeometry(12, self.height() - 29, self.width() - 24, 24)

    def set_loading(self, message="正在载入预览…"):
        self.set_mesh(None, message)

    def set_view(self, yaw, pitch, zoom):
        self._yaw, self._pitch, self._zoom = yaw, pitch, zoom
        self.update()

    def reset_view(self):
        self.set_view(-35.0, 24.0, 1.0)
        self.view_changed.emit(self._yaw, self._pitch, self._zoom)

    def initializeGL(self):
        gl = ctypes.WinDLL("opengl32.dll")
        signatures = {
            "glClearColor": (None, [ctypes.c_float] * 4),
            "glClear": (None, [ctypes.c_uint]),
            "glEnable": (None, [ctypes.c_uint]),
            "glDisable": (None, [ctypes.c_uint]),
            "glDepthFunc": (None, [ctypes.c_uint]),
            "glDepthMask": (None, [ctypes.c_ubyte]),
            "glViewport": (None, [ctypes.c_int] * 4),
            "glMatrixMode": (None, [ctypes.c_uint]),
            "glLoadIdentity": (None, []),
            "glOrtho": (None, [ctypes.c_double] * 6),
            "glRotatef": (None, [ctypes.c_float] * 4),
            "glScalef": (None, [ctypes.c_float] * 3),
            "glColor4f": (None, [ctypes.c_float] * 4),
            "glLightfv": (None, [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]),
            "glLightModeli": (None, [ctypes.c_uint, ctypes.c_int]),
            "glColorMaterial": (None, [ctypes.c_uint, ctypes.c_uint]),
            "glEnableClientState": (None, [ctypes.c_uint]),
            "glDisableClientState": (None, [ctypes.c_uint]),
            "glVertexPointer": (None, [ctypes.c_int, ctypes.c_uint, ctypes.c_int, ctypes.c_void_p]),
            "glNormalPointer": (None, [ctypes.c_uint, ctypes.c_int, ctypes.c_void_p]),
            "glDrawArrays": (None, [ctypes.c_uint, ctypes.c_int, ctypes.c_int]),
            "glGetString": (ctypes.c_char_p, [ctypes.c_uint]),
            "glGetError": (ctypes.c_uint, []),
        }
        for name, (result, arguments) in signatures.items():
            function = getattr(gl, name)
            function.restype, function.argtypes = result, arguments
        self._gl = gl
        self.renderer = (gl.glGetString(0x1F01) or b"unknown").decode(errors="replace")
        # Upload static vertex/normal arrays once. Rotation then changes only matrices.
        try:
            context = self.context()
            def proc(name, result, *args):
                address = context.getProcAddress(name)
                if not address:
                    raise RuntimeError(name)
                return ctypes.WINFUNCTYPE(result, *args)(int(address))
            self._buffer_functions = (
                proc("glGenBuffers", None, ctypes.c_int, ctypes.c_void_p),
                proc("glBindBuffer", None, ctypes.c_uint, ctypes.c_uint),
                proc("glBufferData", None, ctypes.c_uint, ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint),
                proc("glDeleteBuffers", None, ctypes.c_int, ctypes.c_void_p),
            )
        except (RuntimeError, TypeError, ValueError):
            self._buffer_functions = None
        self.context().aboutToBeDestroyed.connect(self._release_buffers)
        self._upload_pending = self._vertices is not None

    def _release_buffers(self):
        if self._buffers is not None and self._buffer_functions:
            self.makeCurrent()
            self._buffer_functions[3](2, self._buffers)
            self._buffers = None
            self.doneCurrent()

    def paintGL(self):
        gl = self._gl
        if gl is None:
            return
        ratio = self.devicePixelRatioF()
        gl.glViewport(0, 0, round(self.width() * ratio), round(self.height() * ratio))
        gl.glClearColor(0.082, 0.102, 0.133, 1.0)
        gl.glDepthMask(1)
        gl.glClear(0x00004000 | 0x00000100)
        gl.glDisable(0x0BE2)  # blending: opaque surfaces
        gl.glDisable(0x0B44)  # show both sides of STL faces
        gl.glEnable(0x0B71)   # depth test: hide rear surfaces
        gl.glDepthFunc(0x0203)
        gl.glMatrixMode(0x1701)
        gl.glLoadIdentity()
        aspect = self.width() / max(1, self.height())
        gl.glOrtho(-0.78 * aspect, 0.78 * aspect, -0.78, 0.78, -10, 10)
        gl.glMatrixMode(0x1700)
        gl.glLoadIdentity()
        gl.glEnable(0x0B50)
        gl.glEnable(0x4000)
        gl.glEnable(0x0BA1)
        gl.glLightModeli(0x0B52, 1)  # two-sided lighting for inconsistent STL winding
        light = (ctypes.c_float * 4)(-0.4, 0.7, 1.0, 0.0)
        ambient = (ctypes.c_float * 4)(0.28, 0.28, 0.28, 1.0)
        gl.glLightfv(0x4000, 0x1203, light)
        gl.glLightfv(0x4000, 0x1200, ambient)
        gl.glEnable(0x0B57)
        gl.glColorMaterial(0x0408, 0x1602)
        gl.glColor4f(self.accent.redF(), self.accent.greenF(), self.accent.blueF(), 1.0)
        gl.glRotatef(self._pitch, 1, 0, 0)
        gl.glRotatef(self._yaw, 0, 1, 0)
        gl.glScalef(self._zoom, self._zoom, self._zoom)
        if self._vertices is not None:
            gl.glEnableClientState(0x8074)
            gl.glEnableClientState(0x8075)
            if self._buffer_functions:
                generate, bind, upload, _delete = self._buffer_functions
                if self._buffers is None:
                    self._buffers = (ctypes.c_uint * 2)()
                    generate(2, self._buffers)
                if self._upload_pending:
                    for buffer, data in zip(self._buffers, (self._vertices, self._normals)):
                        bind(0x8892, buffer)
                        upload(0x8892, data.nbytes, ctypes.c_void_p(data.ctypes.data), 0x88E4)
                    self._upload_pending = False
                bind(0x8892, self._buffers[0])
                gl.glVertexPointer(3, 0x1406, 0, None)
                bind(0x8892, self._buffers[1])
                gl.glNormalPointer(0x1406, 0, None)
            else:
                gl.glVertexPointer(3, 0x1406, 0, ctypes.c_void_p(self._vertices.ctypes.data))
                gl.glNormalPointer(0x1406, 0, ctypes.c_void_p(self._normals.ctypes.data))
            gl.glDrawArrays(0x0004, 0, len(self._vertices))
            if self._buffer_functions:
                self._buffer_functions[1](0x8892, 0)
            gl.glDisableClientState(0x8074)
            gl.glDisableClientState(0x8075)
        gl.glDisable(0x0B50)
        gl.glDisable(0x0B71)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._last_pos = event.position()

    def mouseMoveEvent(self, event):
        if self._last_pos is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        delta = event.position() - self._last_pos
        self._last_pos = event.position()
        self._yaw += delta.x() * 0.55
        self._pitch = max(-89, min(89, self._pitch + delta.y() * 0.55))
        self.view_changed.emit(self._yaw, self._pitch, self._zoom)
        self.update()

    def mouseReleaseEvent(self, event):
        self._last_pos = None

    def mouseDoubleClickEvent(self, event):
        self.reset_view()

    def wheelEvent(self, event):
        factor = 1.1 if event.angleDelta().y() > 0 else 1 / 1.1
        self._zoom = max(0.35, min(3.5, self._zoom * factor))
        self.view_changed.emit(self._yaw, self._pitch, self._zoom)
        self.update()
