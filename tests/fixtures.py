from pathlib import Path
from tempfile import mkdtemp

import pymeshlab

from stl_batch_simplifier_qt import save_binary_stl_unicode_safe


def test_run_dir(prefix: str) -> Path:
    """Keep generated meshes and screenshots outside tracked source."""
    root = Path(__file__).resolve().parents[1] / ".test-artifacts"
    root.mkdir(exist_ok=True)
    return Path(mkdtemp(prefix=f"{prefix}_", dir=root))


def write_sphere(path: Path, subdivisions: int = 3) -> None:
    meshes = pymeshlab.MeshSet()
    meshes.apply_filter("create_sphere", subdiv=subdivisions)
    save_binary_stl_unicode_safe(meshes.current_mesh(), path)
