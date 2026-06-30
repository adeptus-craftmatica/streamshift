from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_LAYOUTS_DIR = Path.home() / ".streamshift" / "stage_layouts"
_FORMAT_VERSION = 1


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "_", name.lower().strip())[:64] or "layout"


class LayoutEntry:
    __slots__ = ("name", "slug", "path")

    def __init__(self, name: str, slug: str, path: Path) -> None:
        self.name = name
        self.slug = slug
        self.path = path


class LayoutRepository:
    """Named layout persistence — one JSON file per layout in ~/.streamshift/stage_layouts/."""

    def __init__(self, directory: Path = _LAYOUTS_DIR) -> None:
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)

    def list_layouts(self) -> list[LayoutEntry]:
        entries: list[LayoutEntry] = []
        for p in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                name = data.get("name") or p.stem
                entries.append(LayoutEntry(name=name, slug=p.stem, path=p))
            except Exception as exc:
                logger.warning("Skipping bad layout file %s: %s", p, exc)
        return entries

    def save_layout(self, name: str, panels: list[dict]) -> LayoutEntry:
        slug = self._unique_slug(name)
        path = self._dir / f"{slug}.json"
        data = {
            "streamshift_layout_version": _FORMAT_VERSION,
            "name": name,
            "panels": panels,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info("Saved layout '%s' → %s", name, path)
        return LayoutEntry(name=name, slug=slug, path=path)

    def load_layout(self, slug: str) -> list[dict] | None:
        path = self._dir / f"{slug}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("panels", [])
        except Exception as exc:
            logger.warning("Could not load layout %s: %s", slug, exc)
            return None

    def delete_layout(self, slug: str) -> None:
        path = self._dir / f"{slug}.json"
        if path.exists():
            path.unlink()
            logger.info("Deleted layout %s", slug)

    def export_layout(self, name: str, panels: list[dict], dest_path: Path) -> None:
        data = {
            "streamshift_layout_version": _FORMAT_VERSION,
            "name": name,
            "panels": panels,
        }
        dest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info("Exported layout to %s", dest_path)

    @staticmethod
    def import_layout(src_path: Path) -> tuple[str, list[dict]] | None:
        try:
            data = json.loads(src_path.read_text(encoding="utf-8"))
            panels = data.get("panels", [])
            name = data.get("name") or src_path.stem
            return name, panels
        except Exception as exc:
            logger.warning("Could not import layout from %s: %s", src_path, exc)
            return None

    def _unique_slug(self, name: str) -> str:
        base = _slug(name)
        slug = base
        i = 2
        while (self._dir / f"{slug}.json").exists():
            slug = f"{base}_{i}"
            i += 1
        return slug
