"""
shloka_source.py — Loads shlokas.csv (as produced by ShlokaManager) and
hands them out one at a time, sequentially or shuffled, with position
persisted so the app resumes where it left off across restarts.

Expected CSV columns (exact names, produced by ShlokaManager):
    Reference_Number, Shloka, Translation
"""

from __future__ import annotations
import csv
import os
import random
import sys
from dataclasses import dataclass
from typing import List, Optional

from .config import config


@dataclass
class Shloka:
    reference: str
    sanskrit: str
    translation: str = ""


class ShlokaSource:
    def __init__(self, csv_path: Optional[str] = None):
        self.csv_path = csv_path or config.get("content/csv_path")
        self._items: List[Shloka] = []
        self._order: List[int] = []
        self._pos: int = 0
        self.reload()

    # ------------------------------------------------------------------
    def reload(self) -> None:
        self._items = self._load_csv(self.csv_path)
        n = len(self._items)
        self._order = list(range(n))
        if config.get("behaviour/order") == "shuffle":
            random.shuffle(self._order)
        self._pos = config.get("content/last_index") % max(n, 1) if n else 0

    def reshuffle(self, force_random: bool = False) -> None:
        """Reset the cycle from scratch — used by the Settings
        'restart random cycle' button so the user can preview from a
        fresh shuffle without waiting or restarting the app.

        force_random=True always produces a new random ordering
        regardless of the behaviour/order setting. Without this, calling
        reshuffle() while behaviour/order == "sequential" just resets
        back to index 0 every time, which makes a button literally
        labelled "restart random cycle" show the same first verse on
        every click — not what it promises."""
        n = len(self._items)
        self._order = list(range(n))
        if force_random or config.get("behaviour/order") == "shuffle":
            random.shuffle(self._order)
        self._pos = 0
        config.set("content/last_index", 0)

    def _load_csv(self, path: str) -> List[Shloka]:
        resolved = self._resolve_csv_path(path)
        if resolved is None:
            print(
                f"[Smriti] WARNING: shlokas CSV not found (tried '{path}' as given, "
                f"and relative to the app folder). Falling back to a single built-in "
                f"verse. Set the correct file via Settings > Content > Browse.",
                file=sys.stderr,
            )
            return [
                Shloka(
                    reference="bg.9.34",
                    sanskrit=(
                        "मन्मना भव मद्भ‍क्तो मद्याजी मां नमस्कुरु ।\n"
                        "मामेवैष्यसि युक्त्वैवमात्मानं मत्परायण: ||"
                    ),
                    translation=(
                        "Engage your mind always in thinking of Me, become "
                        "My devotee, offer obeisances to Me and worship Me."
                    ),
                )
            ]

        items: List[Shloka] = []
        with open(resolved, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sanskrit = (row.get("Shloka") or "").strip()
                if not sanskrit:
                    continue
                items.append(
                    Shloka(
                        reference=(row.get("Reference_Number") or "").strip(),
                        sanskrit=sanskrit,
                        translation=(row.get("Translation") or "").strip(),
                    )
                )
        if not items:
            print(
                f"[Smriti] WARNING: '{resolved}' was found but produced zero usable "
                f"rows — check the header names are exactly 'Reference_Number', "
                f"'Shloka', 'Translation'.",
                file=sys.stderr,
            )
        return items

    @staticmethod
    def _resolve_csv_path(path: str) -> Optional[str]:
        """A relative content/csv_path is resolved against the current
        working directory first (matches the QFileDialog-selected path
        behaviour), then against the app's own folder, since launching
        via double-click can leave the cwd somewhere unrelated (e.g. the
        user's home folder) even though a shlokas.csv sits right next
        to main.py."""
        if os.path.isabs(path):
            return path if os.path.exists(path) else None
        if os.path.exists(path):
            return os.path.abspath(path)
        app_dir_candidate = os.path.join(os.path.dirname(os.path.dirname(__file__)), path)
        if os.path.exists(app_dir_candidate):
            return app_dir_candidate
        return None

    # ------------------------------------------------------------------
    def current(self) -> Optional[Shloka]:
        if not self._items:
            return None
        idx = self._order[self._pos % len(self._order)]
        return self._items[idx]

    def advance(self, step: int = 1) -> Optional[Shloka]:
        if not self._items:
            return None
        self._pos = (self._pos + step) % len(self._order)
        config.set("content/last_index", self._pos)
        return self.current()

    def next(self) -> Optional[Shloka]:
        return self.advance(1)

    def previous(self) -> Optional[Shloka]:
        return self.advance(-1)

    def count(self) -> int:
        return len(self._items)
