from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from .paths import RuntimePaths
from .util import atomic_write_json, read_json, utc_now_iso

ALLOWED_STATUS = {"fresh", "needs_reprocess", "failed", "needs_ocr"}
ALLOWED_PLACEMENT = {"normal", "long-term"}


@dataclass
class BundleRecord:
    id: str
    title: str
    category: str
    bundle_path: str
    source_path: str
    source_sha256: str
    source_mtime: str
    document_md: str
    figures_path: str
    converter: str
    status: str
    placement: str
    pinned: bool
    first_seen_at: str
    last_processed_at: str
    last_accessed_at: str
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict) -> "BundleRecord":
        data = dict(payload)
        data.setdefault("warnings", [])
        data.setdefault("status", "fresh")
        data.setdefault("placement", "normal")
        if data["status"] not in ALLOWED_STATUS:
            data["status"] = "failed"
        if data["placement"] not in ALLOWED_PLACEMENT:
            data["placement"] = "normal"
        return cls(**data)

    def to_dict(self) -> dict:
        output = asdict(self)
        output["warnings"] = sorted(set(output.get("warnings", [])))
        return output


@dataclass
class CategoryManifest:
    schema_version: int
    category: str
    generated_at: str
    bundles: list[BundleRecord] = field(default_factory=list)

    @classmethod
    def empty(cls, category: str) -> "CategoryManifest":
        return cls(schema_version=1, category=category, generated_at=utc_now_iso(), bundles=[])

    @classmethod
    def from_dict(cls, payload: dict, category: str) -> "CategoryManifest":
        bundles = [BundleRecord.from_dict(item) for item in payload.get("bundles", [])]
        bundles.sort(key=lambda item: item.id)
        return cls(
            schema_version=int(payload.get("schema_version", 1)),
            category=payload.get("category", category),
            generated_at=payload.get("generated_at", utc_now_iso()),
            bundles=bundles,
        )

    def to_dict(self) -> dict:
        self.generated_at = utc_now_iso()
        self.bundles.sort(key=lambda item: item.id)
        return {
            "schema_version": self.schema_version,
            "category": self.category,
            "generated_at": self.generated_at,
            "bundles": [item.to_dict() for item in self.bundles],
        }


def manifest_path(paths: RuntimePaths, category: str) -> Path:
    return paths.category_root(category) / "_manifest.json"


def index_path(paths: RuntimePaths, category: str) -> Path:
    return paths.category_root(category) / "_index.md"


def load_manifest(paths: RuntimePaths, category: str) -> CategoryManifest:
    payload = read_json(manifest_path(paths, category), default={})
    if not payload:
        return CategoryManifest.empty(category)
    return CategoryManifest.from_dict(payload, category=category)


def save_manifest(paths: RuntimePaths, manifest: CategoryManifest) -> Path:
    path = manifest_path(paths, manifest.category)
    atomic_write_json(path, manifest.to_dict())
    return path


def get_bundle(manifest: CategoryManifest, bundle_id: str) -> BundleRecord | None:
    for bundle in manifest.bundles:
        if bundle.id == bundle_id:
            return bundle
    return None


def replace_bundle(manifest: CategoryManifest, record: BundleRecord) -> bool:
    for idx, current in enumerate(manifest.bundles):
        if current.id == record.id:
            manifest.bundles[idx] = record
            return False
    manifest.bundles.append(record)
    manifest.bundles.sort(key=lambda item: item.id)
    return True


def drop_bundle(manifest: CategoryManifest, bundle_id: str) -> bool:
    initial = len(manifest.bundles)
    manifest.bundles = [bundle for bundle in manifest.bundles if bundle.id != bundle_id]
    return len(manifest.bundles) != initial


def iter_manifests(paths: RuntimePaths, categories: Iterable[str]) -> list[CategoryManifest]:
    return [load_manifest(paths, category) for category in categories]
