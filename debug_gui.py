import sys
from PySide6.QtWidgets import QApplication, QPushButton
from gui import MainWindow

app = QApplication(sys.argv)
window = MainWindow()

print("--- Button List ---")
buttons = window.findChildren(QPushButton)
found = False
for btn in buttons:
    print(f"Button: '{btn.text()}' | Visible: {btn.isVisible()} | Parent: {btn.parent()}")
    if "LUT" in btn.text():
        found = True

if found:
    print("\n[SUCCESS] LUT Button found in widget tree.")
else:
    print("\n[FAILURE] LUT Button NOT found in widget tree.")
