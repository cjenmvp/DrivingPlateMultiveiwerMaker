import sys
import os
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QLineEdit, QPushButton, QFileDialog, QGridLayout, 
    QFrame, QTextEdit, QProgressBar, QListWidget, QComboBox, QGroupBox, QMessageBox,
    QAbstractItemView, QDialog, QScrollArea
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QPalette

class DarkPalette(QPalette):
    def __init__(self):
        super().__init__()
        self.setColor(QPalette.Window, QColor(45, 45, 45))
        self.setColor(QPalette.WindowText, Qt.white)
        self.setColor(QPalette.Base, QColor(25, 25, 25))
        self.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
        self.setColor(QPalette.ToolTipBase, Qt.white)
        self.setColor(QPalette.ToolTipText, Qt.white)
        self.setColor(QPalette.Text, Qt.white)
        self.setColor(QPalette.Button, QColor(45, 45, 45))
        self.setColor(QPalette.ButtonText, Qt.white)
        self.setColor(QPalette.BrightText, Qt.red)
        self.setColor(QPalette.Link, QColor(42, 130, 218))
        self.setColor(QPalette.Highlight, QColor(42, 130, 218))
        self.setColor(QPalette.HighlightedText, Qt.black)

class SlotWidget(QFrame):
    file_changed = Signal(int, str) # slot_idx, file_path

    def __init__(self, slot_idx, label_text):
        super().__init__()
        self.slot_idx = slot_idx
        self.setFrameShape(QFrame.Box)
        self.setLineWidth(1)
        self.setStyleSheet("background-color: #1e1e1e; border: 1px solid #555;")
        self.setAcceptDrops(True) # Enable Drag & Drop
        
        layout = QVBoxLayout(self)
        
        self.idx_label = QLabel(f"슬롯 {slot_idx + 1}") 
        self.idx_label.setStyleSheet("color: #888; font-size: 10px;")
        
        self.pattern_label = QLabel(label_text)
        self.pattern_label.setStyleSheet("color: #aaa; font-weight: bold;")
        self.pattern_label.setAlignment(Qt.AlignCenter)
        
        self.file_label = QLabel("대기 중... (클릭/드래그)")
        self.file_label.setStyleSheet("color: #555; font-style: italic;")
        self.file_label.setWordWrap(True)
        self.file_label.setAlignment(Qt.AlignCenter)
        
        layout.addWidget(self.idx_label)
        layout.addWidget(self.pattern_label)
        layout.addWidget(self.file_label)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        if files:
            # Take the first file
            filepath = files[0]
            if os.path.isfile(filepath) and filepath.lower().endswith(('.mp4', '.mov', '.mkv', '.avi')):
                self.file_changed.emit(self.slot_idx, filepath)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            filepath, _ = QFileDialog.getOpenFileName(
                self, "비디오 파일 선택", "", "Video Files (*.mp4 *.mov *.mkv *.avi)"
            )
            if filepath:
                self.file_changed.emit(self.slot_idx, filepath)
        
    def set_file(self, filename):
        if filename:
            self.file_label.setText(os.path.basename(filename))
            self.file_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        else:
            self.file_label.setText("누락됨 (블랙)")
            self.file_label.setStyleSheet("color: #FF5252; font-weight: bold;")

class DragDropListWidget(QListWidget):
    folders_dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setStyleSheet("background: #222; color: #eee; border: 1px solid #444;")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        folders = []
        for url in urls:
            path = url.toLocalFile()
            if os.path.isdir(path):
                folders.append(path)
        
        if folders:
            self.folders_dropped.emit(folders)


class LutConfigDialog(QDialog):
    def __init__(self, parent=None, current_mapping=None, current_luts=None):
        super().__init__(parent)
        self.setWindowTitle("LUT 설정")
        self.resize(600, 500)
        self.setStyleSheet("background-color: #2d2d2d; color: white;")
        
        self.lut_mapping = current_luts.copy() if current_luts else {}
        self.rows = []
        
        layout = QVBoxLayout(self)
        
        # Scroll Area for 9 slots
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background-color: #222; border: none;")
        scroll_content = QWidget()
        self.grid_layout = QGridLayout(scroll_content)
        self.grid_layout.setSpacing(10)
        
        # Headers
        self.grid_layout.addWidget(QLabel("슬롯"), 0, 0)
        self.grid_layout.addWidget(QLabel("파일"), 0, 1)
        self.grid_layout.addWidget(QLabel("적용된 LUT"), 0, 2)
        self.grid_layout.addWidget(QLabel("변경"), 0, 3)
        
        slot_labels = [
            "1 (Top-L)", "2 (Top-C)", "3 (Top-R)",
            "4 (Mid-L)", "5 (Center)", "6 (Mid-R)",
            "7 (Bot-L)", "8 (Bot-C)", "9 (Bot-R)"
        ]
        
        for i in range(9):
            # Label
            lbl_slot = QLabel(slot_labels[i])
            lbl_slot.setStyleSheet("color: #aaa; font-weight: bold;")
            
            # Filename
            file_path = current_mapping.get(i)
            filename = os.path.basename(file_path) if file_path else "파일 없음"
            lbl_file = QLabel(filename)
            lbl_file.setStyleSheet("color: #ddd;" if file_path else "color: #555; font-style: italic;")
            
            # LUT Path
            current_lut = self.lut_mapping.get(i)
            lut_name = os.path.basename(current_lut) if current_lut else "없음 (Rec.709)"
            lbl_lut = QLabel(lut_name)
            lbl_lut.setStyleSheet("color: #4CAF50;" if current_lut else "color: #777;")
            
            # Btns
            btn_frame = QFrame()
            btn_layout = QHBoxLayout(btn_frame)
            btn_layout.setContentsMargins(0,0,0,0)
            
            btn_browse = QPushButton("선택...")
            btn_browse.setStyleSheet("background-color: #2196F3; padding: 4px 8px; border-radius: 3px;")
            btn_browse.clicked.connect(lambda _, idx=i, lbl=lbl_lut: self.browse_lut(idx, lbl))
            
            btn_clear = QPushButton("해제")
            btn_clear.setStyleSheet("background-color: #555; padding: 4px 8px; border-radius: 3px;")
            btn_clear.clicked.connect(lambda _, idx=i, lbl=lbl_lut: self.clear_lut(idx, lbl))
            
            btn_layout.addWidget(btn_browse)
            btn_layout.addWidget(btn_clear)
            
            self.grid_layout.addWidget(lbl_slot, i+1, 0)
            self.grid_layout.addWidget(lbl_file, i+1, 1)
            self.grid_layout.addWidget(lbl_lut, i+1, 2)
            self.grid_layout.addWidget(btn_frame, i+1, 3)
            
            self.rows.append({
                "lut_label": lbl_lut
            })
            
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
        
        # Bottom Actions
        bot_layout = QHBoxLayout()
        
        btn_all = QPushButton("전체 슬롯에 동일 LUT 적용...")
        btn_all.setStyleSheet("background-color: #FF9800; padding: 8px;")
        btn_all.clicked.connect(self.apply_lut_all)
        
        btn_reset_all = QPushButton("전체 해제")
        btn_reset_all.setStyleSheet("background-color: #607D8B; padding: 8px;")
        btn_reset_all.clicked.connect(self.clear_all)
        
        bot_layout.addWidget(btn_all)
        bot_layout.addWidget(btn_reset_all)
        bot_layout.addStretch()
        
        btn_ok = QPushButton("확인")
        btn_ok.setStyleSheet("background-color: #4CAF50; padding: 8px 20px; font-weight: bold;")
        btn_ok.clicked.connect(self.accept)
        
        btn_cancel = QPushButton("취소")
        btn_cancel.setStyleSheet("background-color: #D32F2F; padding: 8px 20px; font-weight: bold;")
        btn_cancel.clicked.connect(self.reject)
        
        bot_layout.addWidget(btn_ok)
        bot_layout.addWidget(btn_cancel)
        
        layout.addLayout(bot_layout)
        
    def browse_lut(self, idx, label_widget):
        path, _ = QFileDialog.getOpenFileName(self, "LUT 파일 선택", "", "LUT Files (*.cube)")
        if path:
            self.lut_mapping[idx] = path
            label_widget.setText(os.path.basename(path))
            label_widget.setStyleSheet("color: #4CAF50;")
            
    def clear_lut(self, idx, label_widget):
        if idx in self.lut_mapping:
            del self.lut_mapping[idx]
        label_widget.setText("없음 (Rec.709)")
        label_widget.setStyleSheet("color: #777;")
        
    def apply_lut_all(self):
        path, _ = QFileDialog.getOpenFileName(self, "전체 적용할 LUT 선택", "", "LUT Files (*.cube)")
        if path:
            for i in range(9):
                self.lut_mapping[i] = path
                self.rows[i]["lut_label"].setText(os.path.basename(path))
                self.rows[i]["lut_label"].setStyleSheet("color: #4CAF50;")
                
    def clear_all(self):
        self.lut_mapping.clear()
        for i in range(9):
            self.rows[i]["lut_label"].setText("없음 (Rec.709)")
            self.rows[i]["lut_label"].setStyleSheet("color: #777;")
        
    def get_mapping(self):
        return self.lut_mapping


class MainWindow(QMainWindow):
    # Signals to be connected in controller
    request_scan = Signal(str)
    request_preview = Signal()
    request_render = Signal()
    request_add_queue = Signal(dict) # {folder, text, mapping, output_path, lut_mapping}
    request_start_queue = Signal()
    request_remove_queue = Signal(int)
    request_lut_settings = Signal()
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CJENMVP 드라이빙플레이트 멀티뷰어 자동생성기 v1.0")
        self.resize(1000, 800)
        
        # Apply Dark Theme
        self.setPalette(DarkPalette())
        
        # Main Widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # 1. Header (Folder Selection)
        header_layout = QHBoxLayout()
        
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("폴더 선택...")
        self.path_input.setStyleSheet("padding: 8px; border-radius: 4px; background: #333; color: white;")
        
        self.browse_btn = QPushButton("찾아보기")
        self.browse_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3; color: white; padding: 8px 16px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #1976D2; }
        """)
        self.browse_btn.clicked.connect(self.browse_folder)
        
        header_layout.addWidget(self.path_input)
        header_layout.addWidget(self.browse_btn)
        main_layout.addLayout(header_layout)

        # 1.5 Output Path (Optional)
        output_layout = QHBoxLayout()
        self.output_input = QLineEdit()
        self.output_input.setPlaceholderText("저장 경로 (비워두면 원본 폴더에 저장)")
        self.output_input.setStyleSheet("padding: 8px; border-radius: 4px; background: #333; color: white;")
        
        self.output_btn = QPushButton("저장 위치 변경")
        self.output_btn.setStyleSheet("""
            QPushButton {
                background-color: #607D8B; color: white; padding: 8px 16px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #546E7A; }
        """)
        self.output_btn.clicked.connect(self.browse_output_folder)
        
        output_layout.addWidget(self.output_input)
        output_layout.addWidget(self.output_btn)
        main_layout.addLayout(output_layout)
        
        # 2. Text Overlay Input
        text_layout = QHBoxLayout()
        text_label = QLabel("오버레이 텍스트:")
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("영상에 넣을 텍스트 (기본값: 폴더명)")
        self.text_input.setStyleSheet("padding: 8px; border-radius: 4px; background: #333; color: white;")
        
        text_layout.addWidget(text_label)
        text_layout.addWidget(self.text_input)
        main_layout.addLayout(text_layout)

        # 3. 3x3 Grid
        self.grid_layout = QGridLayout()
        self.slots = []
        
        # Grid Mapping for UI visual
        # Row 1: 0, 1, 2
        # Row 2: 3, 4, 5
        # Row 3: 6, 7, 8
        labels = [
            "10_", "12_", "02_",
            "09_", "Center (Top/13)", "03_",
            "08_", "06_", "04_"
        ]
        
        for i in range(9):
            row = i // 3
            col = i % 3
            widget = SlotWidget(i, labels[i])
            self.grid_layout.addWidget(widget, row, col)
            self.slots.append(widget)
            
        main_layout.addLayout(self.grid_layout, stretch=1)

        # 4. Actions
        action_layout = QHBoxLayout()
        
        self.preview_btn = QPushButton("프리뷰 생성 (1초)")
        self.preview_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800; color: white; padding: 12px; border-radius: 4px; font-weight: bold;
            }
            QPushButton:hover { background-color: #F57C00; }
        """)
        self.preview_btn.clicked.connect(self.request_preview.emit)
        
        self.render_btn = QPushButton("렌더링 시작")
        self.render_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50; color: white; padding: 12px; border-radius: 4px; font-weight: bold;
            }
            QPushButton:hover { background-color: #388E3C; }
        """)
        self.render_btn.clicked.connect(self.request_render.emit)
        
        # Codec Selection
        self.codec_combo = QComboBox()
        self.codec_combo.addItems(["H.265 (HEVC)", "H.264"])
        self.codec_combo.setCurrentIndex(0) # Default to H.265
        self.codec_combo.setToolTip("H.265: 고화질/저용량 (추천)\nH.264: 호환성 우수")
        self.codec_combo.setStyleSheet("padding: 10px;")
        
        self.lut_btn = QPushButton("LUT 설정")
        self.lut_btn.setStyleSheet("""
            QPushButton {
                 background-color: #673AB7; color: white; padding: 12px; border-radius: 4px; font-weight: bold;
            }
            QPushButton:hover { background-color: #5E35B1; }
        """)
        self.lut_btn.clicked.connect(self.request_lut_settings.emit)
        
        action_layout.addWidget(self.codec_combo)
        action_layout.addWidget(self.lut_btn)
        action_layout.addWidget(self.preview_btn)
        action_layout.addWidget(self.render_btn)
        
        # Add Queue Button
        self.add_queue_btn = QPushButton("대기열 추가")
        self.add_queue_btn.setStyleSheet("""
            QPushButton {
                background-color: #9C27B0; color: white; padding: 12px; border-radius: 4px; font-weight: bold;
            }
            QPushButton:hover { background-color: #7B1FA2; }
        """)
        self.add_queue_btn.clicked.connect(self.emit_add_queue)
        action_layout.addWidget(self.add_queue_btn)
        
        main_layout.addLayout(action_layout)

        # 4.5 Queue List Area
        queue_group = QGroupBox("작업 대기열 (폴더를 드래그해서 추가하세요)")
        queue_group.setStyleSheet("QGroupBox { font-weight: bold; color: white; border: 1px solid #555; margin-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }")
        queue_layout = QVBoxLayout(queue_group)
        
        self.queue_list = DragDropListWidget()
        queue_layout.addWidget(self.queue_list)
        
        queue_btn_layout = QHBoxLayout()
        self.btn_queue_start = QPushButton("대기열 일괄 처리 시작")
        self.btn_queue_start.setStyleSheet("background-color: #E91E63; color: white; padding: 8px;")
        self.btn_queue_start.clicked.connect(self.request_start_queue.emit)
        
        self.btn_queue_remove = QPushButton("선택 항목 삭제")
        self.btn_queue_remove.setStyleSheet("background-color: #555; color: white; padding: 8px;")
        self.btn_queue_remove.clicked.connect(self.remove_queue_item)
        
        queue_btn_layout.addWidget(self.btn_queue_start)
        queue_btn_layout.addWidget(self.btn_queue_remove)
        queue_layout.addLayout(queue_btn_layout)
        
        main_layout.addWidget(queue_group)

        # 5. Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #555;
                border-radius: 5px;
                text-align: center;
                color: white;
                background-color: #222;
            }
            QProgressBar::chunk {
                background-color: #2196F3;
                width: 10px;
            }
        """)
        main_layout.addWidget(self.progress_bar)

        # 5. Logs
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumHeight(150)
        self.log_area.setStyleSheet("background: #111; color: #0f0; font-family: monospace;")
        main_layout.addWidget(self.log_area)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "폴더 선택")
        if folder:
            self.path_input.setText(folder)
            
            # Default text: Folder Name (remove _nclc if present)
            # Default text: Folder Name (remove _nclc, _h265 if present)
            folder_name = folder.replace("\\", "/").split("/")[-1]
            default_text = folder_name
            for rem in ["_nclc", "_h265", "_H265"]:
                default_text = default_text.replace(rem, "")
            self.text_input.setText(default_text)
            
            self.request_scan.emit(folder)

    def browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "저장 위치 선택")
        if folder:
            self.output_input.setText(folder)

    def emit_add_queue(self):
        # We need to gather current state data
        # Since View doesn't hold 'mapping', we must ask Controller or Controller should handle the collection.
        # But 'add_queue' usually implies 'Add CURRENT CONFIG to queue'.
        # We will emit a signal and let Controller read the UI state and its own mapping state to form the job.
        # We pass a simple dict with UI overrides if any.
        self.request_add_queue.emit({
            "text": self.text_input.text(),
            "output_root": self.output_input.text()
        })

    def remove_queue_item(self):
        row = self.queue_list.currentRow()
        if row >= 0:
            self.request_remove_queue.emit(row)
            self.queue_list.takeItem(row)

    def update_slots(self, file_map):
        for idx, filepath in file_map.items():
            filename = filepath.split(os.sep)[-1] if filepath else None
            # Ensure SlotWidget knows it's getting None if filepath is empty string
            if not filename: filename = None 
            self.slots[idx].set_file(filename)
            
    def log(self, message):
        self.log_area.append(message)
