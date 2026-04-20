import sys
import csv
import re
import os
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QMessageBox, QHeaderView, QAbstractItemView,
    QFileDialog
)
from PySide6.QtGui import QAction, QFont
from PySide6.QtCore import Qt

class ShlokaManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_file = None
        self.unsaved_changes = False
        self.shlokas_data = []

        self.resize(1000, 800)
        
        self.create_menu()
        self.init_ui()
        self.update_title()
        
        self.statusBar().showMessage("Ready")

    def update_title(self):
        title = "Shloka Manager"
        if self.current_file:
            file_name = os.path.basename(self.current_file)
            title += f" - {file_name}"
        else:
            title += " - Untitled"
            
        if self.unsaved_changes:
            title += " *"
            
        self.setWindowTitle(title)

    def set_unsaved(self, state=True):
        self.unsaved_changes = state
        self.update_title()

    def create_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")

        open_action = QAction("Open...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_file)
        file_menu.addAction(open_action)

        save_action = QAction("Save", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_file)
        file_menu.addAction(save_action)

        save_as_action = QAction("Save As...", self)
        save_as_action.setShortcut("Ctrl+Shift+S")
        save_as_action.triggered.connect(self.save_as_file)
        file_menu.addAction(save_as_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def init_ui(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)

        # --- Input Form ---
        form_layout = QVBoxLayout()
        
        self.ref_input = QLineEdit()
        self.ref_input.setPlaceholderText("e.g., bg.1.1")
        form_layout.addWidget(QLabel("Reference Number:"))
        form_layout.addWidget(self.ref_input)

        self.shloka_input = QTextEdit()
        self.shloka_input.setPlaceholderText("Enter Shloka in Devanagari/Sanskrit...")
        self.shloka_input.setMaximumHeight(80)
        form_layout.addWidget(QLabel("Shloka:"))
        form_layout.addWidget(self.shloka_input)

        self.trans_input = QTextEdit()
        self.trans_input.setPlaceholderText("Enter English translation...")
        self.trans_input.setMaximumHeight(80)
        form_layout.addWidget(QLabel("Translation:"))
        form_layout.addWidget(self.trans_input)

        main_layout.addLayout(form_layout)

        # --- Action Buttons ---
        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("Add New")
        self.btn_update = QPushButton("Update Selected")
        self.btn_delete = QPushButton("Delete Selected")
        self.btn_clear = QPushButton("Clear Form")

        self.btn_add.clicked.connect(self.add_shloka)
        self.btn_update.clicked.connect(self.update_shloka)
        self.btn_delete.clicked.connect(self.delete_shloka)
        self.btn_clear.clicked.connect(self.clear_form)

        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_update)
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addWidget(self.btn_clear)
        main_layout.addLayout(btn_layout)

        # --- Search Bar ---
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by Reference, Shloka, or Translation...")
        self.search_input.textChanged.connect(self.filter_table)
        search_layout.addWidget(QLabel("Search:"))
        search_layout.addWidget(self.search_input)
        main_layout.addLayout(search_layout)

        # --- Table View ---
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Reference Number", "Shloka", "Translation"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.populate_form_from_table)
        main_layout.addWidget(self.table)

        self.setCentralWidget(main_widget)

    # --- Utility Functions ---
    def normalize_text(self, text):
        if not text:
            return ""
        cleaned_text = re.sub(r'[\s,\.\-\'"|।॥!?;:ऽ\u200c\u200d]+', '', text).lower()
        return cleaned_text

    def is_valid_reference(self, ref):
        """
        Hard Stop Validation:
        Must start with letters, followed by a dot, followed by numbers.
        Can have multiple dot-number sequences.
        NO spaces, NO double dots, NO trailing dots.
        """
        pattern = r'^[a-zA-Z]+\.\d+(?:\.\d+)*$'
        return bool(re.match(pattern, ref))

    def check_smriti6_warning(self, ref):
        """
        Soft Warning:
        Checks if the validated reference starts with something other than 'bg' or 'sb'.
        """
        prefix = ref.split('.')[0].lower()
        return prefix not in ['bg', 'sb']

    def clear_form(self):
        self.ref_input.clear()
        self.shloka_input.clear()
        self.trans_input.clear()
        self.table.clearSelection()
        self.statusBar().showMessage("Form cleared.", 3000)

    def populate_form_from_table(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if selected_rows:
            row = selected_rows[0].row()
            self.ref_input.setText(self.table.item(row, 0).text())
            self.shloka_input.setPlainText(self.table.item(row, 1).text())
            self.trans_input.setPlainText(self.table.item(row, 2).text())

    def check_unsaved_changes(self):
        if not self.unsaved_changes:
            return True

        reply = QMessageBox.warning(
            self, 'Unsaved Changes',
            'You have unsaved changes. Do you want to save them before proceeding?',
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save
        )

        if reply == QMessageBox.Save:
            return self.save_file()
        elif reply == QMessageBox.Discard:
            return True
        else:
            return False

    # --- File Operations ---
    def open_file(self):
        if not self.check_unsaved_changes():
            return

        file_path, _ = QFileDialog.getOpenFileName(self, "Open Shlokas CSV", "", "CSV Files (*.csv);;All Files (*)")
        if not file_path:
            return

        temp_data = []
        try:
            with open(file_path, mode='r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    temp_data.append({
                        "Reference_Number": row.get("Reference_Number", "").strip(),
                        "Shloka": row.get("Shloka", "").strip(),
                        "Translation": row.get("Translation", "").strip()
                    })
            
            self.shlokas_data = temp_data
            self.current_file = file_path
            self.set_unsaved(False)
            self.search_input.clear()
            self.refresh_table()
            self.clear_form()
            self.statusBar().showMessage(f"Loaded {len(self.shlokas_data)} shlokas from {os.path.basename(file_path)}", 5000)
            
        except Exception as e:
            QMessageBox.critical(self, "Error Loading File", f"Failed to load CSV:\n{str(e)}")
            self.statusBar().showMessage("Error loading file.", 5000)

    def save_file(self):
        if not self.current_file:
            return self.save_as_file()

        try:
            with open(self.current_file, mode='w', encoding='utf-8', newline='') as file:
                writer = csv.DictWriter(file, fieldnames=["Reference_Number", "Shloka", "Translation"])
                writer.writeheader()
                writer.writerows(self.shlokas_data)
            self.set_unsaved(False)
            self.statusBar().showMessage("File saved successfully.", 4000)
            return True
        except Exception as e:
            QMessageBox.critical(self, "Error Saving File", f"Failed to save CSV:\n{str(e)}")
            self.statusBar().showMessage("Error saving file.", 5000)
            return False

    def save_as_file(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Shlokas CSV As", "shlokas.csv", "CSV Files (*.csv)")
        if not file_path:
            return False
            
        self.current_file = file_path
        return self.save_file()

    def refresh_table(self, data_to_show=None):
        if data_to_show is None:
            data_to_show = self.shlokas_data

        self.table.setRowCount(0)
        for row_idx, row_data in enumerate(data_to_show):
            self.table.insertRow(row_idx)
            self.table.setItem(row_idx, 0, QTableWidgetItem(row_data["Reference_Number"]))
            self.table.setItem(row_idx, 1, QTableWidgetItem(row_data["Shloka"]))
            self.table.setItem(row_idx, 2, QTableWidgetItem(row_data["Translation"]))

    def is_duplicate(self, ref, shloka, ignore_index=-1):
        norm_ref_to_check = self.normalize_text(ref)
        norm_shloka_to_check = self.normalize_text(shloka)

        for i, item in enumerate(self.shlokas_data):
            if i == ignore_index:
                continue
            
            existing_ref = self.normalize_text(item["Reference_Number"])
            existing_shloka = self.normalize_text(item["Shloka"])

            if norm_ref_to_check and norm_ref_to_check == existing_ref:
                return True, f"Reference Number '{item['Reference_Number']}' already exists!"
            
            if norm_shloka_to_check and norm_shloka_to_check == existing_shloka:
                return True, f"This exact Shloka is already saved under reference '{item['Reference_Number']}'!"
                
        return False, ""

    # --- CRUD Actions ---
    def add_shloka(self):
        ref = self.ref_input.text().strip(" '")
        shloka = self.shloka_input.toPlainText().strip(" '")
        trans = self.trans_input.toPlainText().strip(" '")

        if not ref or not shloka or not trans:
            QMessageBox.warning(self, "Input Error", "All fields must contain valid text (at least 1 non-whitespace character)!")
            return

        # Hard Stop: Structural Format Check
        if not self.is_valid_reference(ref):
            QMessageBox.critical(self, "Invalid Reference Format", 
                "The reference number format is incorrect.\n\n"
                "Rules:\n"
                "- Must start with text.\n"
                "- Separated ONLY by single dots (e.g., bg.1.1 or xyz.12.3.1).\n"
                "- No spaces, no consecutive dots, and no trailing dots.")
            return

        is_dup, msg = self.is_duplicate(ref, shloka)
        if is_dup:
            QMessageBox.warning(self, "Duplicate Found", msg)
            return

        self.shlokas_data.append({
            "Reference_Number": ref,
            "Shloka": shloka,
            "Translation": trans
        })
        
        self.set_unsaved(True)
        self.refresh_table()
        self.clear_form()
        
        # Soft Warning: Prefix Check
        if self.check_smriti6_warning(ref):
            self.statusBar().showMessage(f"Added: {ref}  [WARNING: Unrecognized prefix might throw an error in Smriti6]", 7000)
        else:
            self.statusBar().showMessage(f"Added new shloka: {ref}", 4000)

    def update_shloka(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "Selection Error", "Please select a shloka from the table to update.")
            return

        table_row = selected_rows[0].row()
        old_ref = self.table.item(table_row, 0).text()
        
        actual_index = next((i for i, item in enumerate(self.shlokas_data) if item["Reference_Number"] == old_ref), -1)
        
        if actual_index == -1:
            return

        new_ref = self.ref_input.text().strip(" '")
        new_shloka = self.shloka_input.toPlainText().strip(" '")
        new_trans = self.trans_input.toPlainText().strip(" '")

        if not new_ref or not new_shloka or not new_trans:
            QMessageBox.warning(self, "Input Error", "All fields must contain valid text (at least 1 non-whitespace character)!")
            return

        # Hard Stop: Structural Format Check
        if not self.is_valid_reference(new_ref):
            QMessageBox.critical(self, "Invalid Reference Format", 
                "The reference number format is incorrect.\n\n"
                "Rules:\n"
                "- Must start with text.\n"
                "- Separated ONLY by single dots (e.g., bg.1.1 or xyz.12.3.1).\n"
                "- No spaces, no consecutive dots, and no trailing dots.")
            return

        is_dup, msg = self.is_duplicate(new_ref, new_shloka, ignore_index=actual_index)
        if is_dup:
            QMessageBox.warning(self, "Duplicate Found", msg)
            return

        self.shlokas_data[actual_index] = {
            "Reference_Number": new_ref,
            "Shloka": new_shloka,
            "Translation": new_trans
        }

        self.set_unsaved(True)
        self.search_input.clear() 
        self.refresh_table()
        
        # Soft Warning: Prefix Check
        if self.check_smriti6_warning(new_ref):
            self.statusBar().showMessage(f"Updated: {new_ref}  [WARNING: Unrecognized prefix might throw an error in Smriti6]", 7000)
        else:
            self.statusBar().showMessage(f"Updated shloka: {new_ref}", 4000)


    def delete_shloka(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "Selection Error", "Please select a shloka to delete.")
            return

        table_row = selected_rows[0].row()
        ref_to_delete = self.table.item(table_row, 0).text()

        reply = QMessageBox.question(self, 'Confirm Delete', 
                                     f"Are you sure you want to delete the shloka '{ref_to_delete}'?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            self.shlokas_data = [item for item in self.shlokas_data if item["Reference_Number"] != ref_to_delete]
            
            self.set_unsaved(True)
            self.search_input.clear()
            self.refresh_table()
            self.clear_form()
            self.statusBar().showMessage(f"Deleted shloka: {ref_to_delete}", 4000)

    def filter_table(self):
        search_text = self.search_input.text().lower()
        if not search_text:
            self.refresh_table()
            self.statusBar().showMessage(f"Showing all {len(self.shlokas_data)} shlokas.", 3000)
            return

        filtered_data = []
        for item in self.shlokas_data:
            if (search_text in item["Reference_Number"].lower() or 
                search_text in item["Shloka"].lower() or 
                search_text in item["Translation"].lower()):
                filtered_data.append(item)
                
        self.refresh_table(filtered_data)
        self.statusBar().showMessage(f"Search results: {len(filtered_data)} found.", 3000)

    # --- Window Events ---
    def closeEvent(self, event):
        if self.check_unsaved_changes():
            event.accept()
        else:
            event.ignore()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    global_font = app.font()
    global_font.setPointSize(11)
    app.setFont(global_font)
    
    window = ShlokaManager()
    window.show()
    sys.exit(app.exec())


