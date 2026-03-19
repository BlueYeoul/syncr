"""File system watcher for auto-sync."""

import time
import threading
from pathlib import Path
from typing import Callable
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from rich.console import Console

console = Console()


class SyncHandler(FileSystemEventHandler):
    """Handles file system events and triggers sync."""

    def __init__(
        self,
        local_root: Path,
        ignore_patterns: list[str],
        on_change: Callable[[list[Path]], None],
        debounce_seconds: float = 1.0,
    ):
        self.local_root = local_root
        self.ignore_patterns = ignore_patterns
        self.on_change = on_change
        self.debounce_seconds = debounce_seconds

        self._pending: set[Path] = set()
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def _rel_path(self, abs_path: str) -> Path | None:
        try:
            return Path(abs_path).relative_to(self.local_root)
        except ValueError:
            return None

    def _should_ignore(self, rel_path: Path) -> bool:
        import fnmatch, os
        path_str = str(rel_path)
        name = rel_path.name
        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(name, pattern):
                return True
            if fnmatch.fnmatch(path_str, pattern):
                return True
            for part in rel_path.parts:
                if fnmatch.fnmatch(part, pattern):
                    return True
        return False

    def _schedule_sync(self):
        """Debounce: wait a bit before syncing to batch rapid changes."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce_seconds, self._flush)
            self._timer.start()

    def _flush(self):
        with self._lock:
            files = list(self._pending)
            self._pending.clear()
            self._timer = None
        if files:
            self.on_change(files)

    def on_modified(self, event: FileSystemEvent):
        if event.is_directory:
            return
        rel = self._rel_path(event.src_path)
        if rel and not self._should_ignore(rel):
            with self._lock:
                self._pending.add(rel)
            self._schedule_sync()

    def on_created(self, event: FileSystemEvent):
        if event.is_directory:
            return
        rel = self._rel_path(event.src_path)
        if rel and not self._should_ignore(rel):
            with self._lock:
                self._pending.add(rel)
            self._schedule_sync()

    def on_moved(self, event: FileSystemEvent):
        if event.is_directory:
            return
        rel = self._rel_path(event.dest_path)
        if rel and not self._should_ignore(rel):
            with self._lock:
                self._pending.add(rel)
            self._schedule_sync()


def start_watching(
    local_root: Path,
    ignore_patterns: list[str],
    on_change: Callable[[list[Path]], None],
    debounce_seconds: float = 1.0,
) -> Observer:
    """Start the file watcher and return the observer (non-blocking)."""
    handler = SyncHandler(
        local_root=local_root,
        ignore_patterns=ignore_patterns,
        on_change=on_change,
        debounce_seconds=debounce_seconds,
    )
    observer = Observer()
    observer.schedule(handler, str(local_root), recursive=True)
    observer.start()
    return observer
