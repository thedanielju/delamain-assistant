from __future__ import annotations

from .manifest import CategoryManifest, index_path
from .paths import RuntimePaths
from .templates import render_category_index
from .util import atomic_write_text, to_rel_posix


def rebuild_category_index(paths: RuntimePaths, manifest: CategoryManifest) -> str:
    rendered = render_category_index(manifest.category, manifest.bundles)
    path = index_path(paths, manifest.category)
    atomic_write_text(path, rendered)
    return to_rel_posix(paths.workspace_root, path)
