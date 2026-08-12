from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = PROJECT_ROOT / "app-config.json"


@dataclass(frozen=True)
class AppPaths:
    root: Path
    state: Path
    notes: Path
    note_history: Path
    cache: Path
    logs: Path
    backups: Path
    exports: Path

    @classmethod
    def from_root(cls, root: Path) -> "AppPaths":
        root = root.expanduser().resolve()
        return cls(
            root=root,
            state=root / "papernote-state.json",
            notes=root / "notes",
            note_history=root / "notes" / ".history",
            cache=root / "cache",
            logs=root / "logs",
            backups=root / "backups",
            exports=root / "exports",
        )

    def ensure(self) -> None:
        for path in (self.root, self.notes, self.note_history, self.cache, self.logs, self.backups, self.exports):
            path.mkdir(parents=True, exist_ok=True)


def _configured_data_root() -> Path:
    env_value = os.environ.get("PAPERNOTE_DATA_DIR")
    if env_value:
        return Path(env_value)
    if CONFIG_FILE.exists():
        try:
            value = json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("data_root")
            if value:
                return Path(value)
        except (OSError, ValueError, TypeError):
            pass
    return PROJECT_ROOT / "library-data"


def data_root_source() -> str:
    if os.environ.get("PAPERNOTE_DATA_DIR"):
        return "environment"
    if CONFIG_FILE.exists():
        try:
            if json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("data_root"):
                return "config"
        except (OSError, ValueError, TypeError):
            pass
    return "default"


PATHS = AppPaths.from_root(_configured_data_root())


def save_data_root(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    if resolved == Path(resolved.anchor):
        raise OSError("不能把磁盘根目录直接作为笔记库，请选择一个专用文件夹")
    with tempfile.NamedTemporaryFile(prefix=".papernote-write-test-", dir=resolved, delete=True):
        pass
    existing: dict[str, object] = {}
    if CONFIG_FILE.exists():
        try:
            existing = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            existing = {}
    existing["data_root"] = str(resolved)
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, CONFIG_FILE)
    return resolved
