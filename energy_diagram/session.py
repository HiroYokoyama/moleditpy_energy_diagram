"""The one diagram being worked on, kept apart from MoleditPy's document.

Values are collected while moving between output files and projects, so the
diagram must outlive File > New and opening other files. It is also written
to ``settings.json`` beside the plugin after every change, the one file the
Plugin Installer keeps on update, so a crash or a forgotten save loses
nothing.
"""

from __future__ import annotations

import json
import logging
import os

from . import model

logger = logging.getLogger(__name__)


class Session:
    def __init__(self, settings_path: str = ""):
        self.settings_path = settings_path
        self.diagram = model.Diagram()
        self.path = ""
        self.dirty = False
        self.last_dir = ""
        self.listeners = []
        self._restore()

    # ------------------------------------------------------------ changes
    def changed(self) -> None:
        self.dirty = True
        self._autosave()
        self._notify()

    def replace(self, diagram: model.Diagram, path: str = "", dirty: bool = False) -> None:
        self.diagram = diagram
        self.path = path
        self.dirty = dirty
        self._autosave()
        self._notify()

    def new(self) -> None:
        self.replace(model.Diagram())

    def _notify(self) -> None:
        for listener in list(self.listeners):
            try:
                listener()
            except Exception:  # pragma: no cover - a closed window
                logger.debug("session listener failed", exc_info=True)

    # -------------------------------------------------------------- files
    def save(self, path: str) -> None:
        if not path.lower().endswith(model.FILE_EXTENSION):
            path += model.FILE_EXTENSION
        text = json.dumps(self.diagram.to_dict(), indent=2, ensure_ascii=False)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
        self.path = path
        self.dirty = False
        self.last_dir = os.path.dirname(path)
        self._autosave()
        self._notify()

    @staticmethod
    def read(path: str) -> model.Diagram:
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"The file is damaged: {exc}") from None
        return model.Diagram.from_dict(data)

    def open(self, path: str) -> None:
        self.replace(self.read(path), path)
        self.last_dir = os.path.dirname(path)
        self._autosave()

    # ----------------------------------------------------------- autosave
    def _settings(self) -> dict:
        if not self.settings_path:
            return {}
        try:
            with open(self.settings_path, encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            logger.warning("Energy diagram: could not read %s: %s", self.settings_path, exc)
            return {}

    def _restore(self) -> None:
        data = self._settings()
        self.last_dir = data.get("last_dir", "") if isinstance(data.get("last_dir"), str) else ""
        saved = data.get("autosave")
        if not isinstance(saved, dict):
            return
        try:
            self.diagram = model.Diagram.from_dict(saved.get("diagram"))
        except ValueError as exc:
            logger.warning("Energy diagram: the autosaved diagram was not restored: %s", exc)
            return
        path = saved.get("path", "")
        self.path = path if isinstance(path, str) else ""
        self.dirty = bool(saved.get("dirty", False))

    def _autosave(self) -> None:
        if not self.settings_path:
            return
        data = self._settings()
        data["last_dir"] = self.last_dir
        data["autosave"] = {
            "diagram": self.diagram.to_dict(),
            "path": self.path,
            "dirty": self.dirty,
        }
        try:
            tmp = self.settings_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=1, ensure_ascii=False)
            os.replace(tmp, self.settings_path)
        except OSError as exc:
            logger.warning("Energy diagram: could not autosave: %s", exc)
