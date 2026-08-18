import sys
import os

def run_manager():
    # We import here so we don't load the manager modules unless needed
    from PySide6.QtWidgets import QApplication
    from src.shloka_manager import ShlokaManager, STYLE_SHEET
    
    app = QApplication(sys.argv)
    
    global_font = app.font()
    global_font.setPointSize(11)
    app.setFont(global_font)
    app.setStyleSheet(STYLE_SHEET)
    
    window = ShlokaManager()
    window.show()
    sys.exit(app.exec())

def run_app():
    from PySide6.QtWidgets import QApplication
    from src.app import SmritiApp
    
    app = QApplication(sys.argv)
    app.setApplicationName("Smriti")
    app.setOrganizationName("Smriti")

    controller = SmritiApp(app)  # noqa: F841 (kept alive for the app's lifetime)

    sys.exit(app.exec())

if __name__ == "__main__":
    # Check the name of the executable to decide which app to launch
    exe_name = os.path.basename(sys.argv[0]).lower()
    
    if "manager" in exe_name:
        run_manager()
    else:
        run_app()
