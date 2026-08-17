#!/usr/bin/env python3
"""
main.py — Entry point for Smriti.

Run with:  python main.py
Package for distribution with PyInstaller (see README.md).
"""
import sys
from PySide6.QtWidgets import QApplication

from smriti.app import SmritiApp


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Smriti")
    app.setOrganizationName("Smriti")

    controller = SmritiApp(app)  # noqa: F841 (kept alive for the app's lifetime)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
