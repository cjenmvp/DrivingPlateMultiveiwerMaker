import sys
import os
import shutil
import subprocess
import re
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QThread, Signal, QObject, Qt

from gui import MainWindow
from ffmpeg_engine import MultiviewerEngine

class FFmpegWorker(QThread):
    conversion_finished = Signal(int, str) # return_code, message
    progress = Signal(int)      # percentage 0-100
    
    def __init__(self, command, total_duration=0, parent=None):
        super().__init__(parent)
        self.command = command
        self.total_duration = total_duration
        
    def run(self):
        import select
        import time
        
        try:
            # Hide console window on Windows
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            # Run command (Use bytes for non-blocking read via select)
            process = subprocess.Popen(
                self.command, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.PIPE,
                text=False, # We deal with bytes for select
                startupinfo=startupinfo,
                bufsize=0 
            )
            
            # Read stderr for progress with timeout
            buffer = b""
            last_activity_time = time.time()
            STALL_TIMEOUT = 30.0 # 30 seconds timeout
            
            while True:
                # Check watchdog
                if time.time() - last_activity_time > STALL_TIMEOUT:
                    process.kill()
                    self.conversion_finished.emit(-1, f"Error: Process stalled for {STALL_TIMEOUT}s (Timeout)")
                    return

                # Non-blocking check
                if os.name == 'nt':
                    pass 
                
                reads = [process.stderr.fileno()]
                ret = select.select(reads, [], [], 1.0) # 1 sec wait
                
                if reads[0] in ret[0]:
                    # Data available
                    chunk = os.read(process.stderr.fileno(), 1024)
                    if not chunk:
                        # EOF
                        if process.poll() is not None:
                            break
                        continue
                    
                    last_activity_time = time.time()
                    buffer += chunk
                    
                    # Process lines (simplistic)
                    msg = buffer.decode('utf-8', errors='ignore')
                    self.parse_progress(msg)
                        
                    # Keep only last part to avoid huge buffer
                    if len(buffer) > 200:
                        buffer = buffer[-50:]
                else:
                    # No data for 1 sec
                    if process.poll() is not None:
                         break
            
            stdout, stderr = process.communicate()
            
            if process.returncode == 0:
                self.conversion_finished.emit(0, "Success")
            else:
                # Capture last part of stderr for debugging
                err_msg = buffer[-1000:].decode('utf-8', errors='ignore') if buffer else "No stderr captured"
                self.conversion_finished.emit(process.returncode, f"Error (Code {process.returncode}):\n{err_msg}")
                
        except Exception as e:
            self.conversion_finished.emit(-1, str(e))

    def parse_progress(self, line):
        # time=00:00:00.00 or time=123.45 => We look for time= expression common in ffmpeg output
        # Example: frame=  192 fps=0.0 q=-1.0 Lsize=    1504kB time=00:00:06.31 bitrate=1953.0kbits/s speed=12.5x
        time_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
        if time_match and self.total_duration > 0:
            h, m, s = map(float, time_match.groups())
            current_seconds = h*3600 + m*60 + s
            percent = int((current_seconds / self.total_duration) * 100)
            self.progress.emit(min(percent, 100))

class AppController(QObject):
    def __init__(self, view, engine):
        super().__init__()
        self.view = view
        self.engine = engine
        
        self.current_mapping = {}
        self.current_folder = ""
        
        # Queue System
        self.job_queue = [] # List of dicts
        self.is_queue_running = False
        
        # Connect Signals
        self.view.request_scan.connect(self.handle_scan)
        self.view.request_preview.connect(self.handle_preview)
        self.view.request_render.connect(self.handle_render)
        self.view.request_add_queue.connect(self.handle_add_queue)
        self.view.request_start_queue.connect(self.handle_start_queue)
        self.view.request_remove_queue.connect(self.handle_remove_queue)
        
        # Connect Drag & Drop Signal
        self.view.queue_list.folders_dropped.connect(self.handle_dropped_folders)
        
        # Connect Slot Manual Override
        for slot in self.view.slots:
            slot.file_changed.connect(self.handle_manual_assignment)
        
    def handle_manual_assignment(self, slot_idx, filepath):
        self.current_mapping[slot_idx] = filepath
        self.view.update_slots(self.current_mapping)
        self.view.log(f"슬롯 {slot_idx + 1} 수동 변경: {os.path.basename(filepath)}")
        
    def handle_scan(self, folder_path):
        self.view.log(f"스캔 중: {folder_path}")
        self.current_folder = folder_path
        self.current_mapping = self.engine.scan_folder(folder_path)
        self.view.update_slots(self.current_mapping)
        self.view.log("스캔 완료.")

    def handle_preview(self):
        self.run_ffmpeg(is_preview=True)

    def handle_render(self):
        self.run_ffmpeg(is_preview=False)

    def handle_dropped_folders(self, folders):
        for folder in folders:
            # 1. Scan the dropped folder
            mapping = self.engine.scan_folder(folder)
            
            # 2. Check if valid (at least one file)
            if not any(mapping.values()):
                self.view.log(f"스킵됨 (파일 없음): {os.path.basename(folder)}")
                continue
                
            # 3. Determine Text
            folder_name = os.path.basename(folder.rstrip(os.sep))
            default_text = folder_name
            for rem in ["_nclc", "_h265", "_H265"]:
                default_text = default_text.replace(rem, "")
            
            # 4. Use output root from UI if set, else folder itself
            output_root = self.view.output_input.text()
            
            job = {
                "folder": folder,
                "mapping": mapping,
                "text": default_text,
                "output_root": output_root,
                "status": "Ready"
            }
            
            self.job_queue.append(job)
            
            # Display
            display_text = f"[{len(self.job_queue)}] {folder_name} (Text: {default_text})"
            self.view.queue_list.addItem(display_text)
            self.view.log(f"대기열 추가됨: {folder_name}")

    def handle_add_queue(self, ui_data):
        if not self.current_mapping or not any(self.current_mapping.values()):
            QMessageBox.warning(self.view, "오류", "유효한 파일이 없어 대기열에 추가할 수 없습니다.")
            return

        job = {
            "folder": self.current_folder,
            "mapping": self.current_mapping.copy(), # Important to copy
            "text": ui_data['text'],
            "output_root": ui_data['output_root'],
            "status": "Ready"
        }
        
        self.job_queue.append(job)
        
        # Display in list
        folder_name = os.path.basename(self.current_folder.rstrip(os.sep))
        display_text = f"[{len(self.job_queue)}] {folder_name} (Text: {job['text']})"
        self.view.queue_list.addItem(display_text)
        self.view.log(f"대기열 추가됨: {folder_name}")

    def handle_remove_queue(self, index):
        if 0 <= index < len(self.job_queue):
            removed = self.job_queue.pop(index)
            self.view.log(f"대기열 삭제됨: {os.path.basename(removed['folder'])}")

    def handle_start_queue(self):
        if not self.job_queue:
            QMessageBox.information(self.view, "알림", "대기열이 비어있습니다.")
            return
            
        if self.is_queue_running:
            return
            
        self.is_queue_running = True
        self.view.btn_queue_start.setEnabled(False)
        self.view.log("=== 대기열 일괄 처리 시작 ===")
        self.process_next_job()

    def process_next_job(self):
        if not self.job_queue:
            self.is_queue_running = False
            self.view.btn_queue_start.setEnabled(True)
            self.view.log("=== 대기열 처리 완료 ===")
            QMessageBox.information(self.view, "완료", "모든 대기열 작업이 완료되었습니다.")
            return

        # Peek first job (Logic: we could pop now, or pop after success. Let's pop now to advance UI)
        # However, typically queue UI updates to 'Processing'.
        # For simplicity, we stick to treating index 0 as current.
        
        job = self.job_queue[0]
        
        # Highlight in UI?
        self.view.queue_list.setCurrentRow(0)
        
        # Run ffmpeg logic
        self.run_ffmpeg_job(job, is_preview=False, is_queue=True)

    def get_unique_output_path(self, folder, filename):
        """
        If filename exists, append _v2, _v3...
        """
        base, ext = os.path.splitext(filename)
        path = os.path.join(folder, filename)
        counter = 2
        
        while os.path.exists(path):
            new_filename = f"{base}_v{counter}{ext}"
            path = os.path.join(folder, new_filename)
            counter += 1
            
        return path

    def run_ffmpeg(self, is_preview):
        # Wrapper for single immediate run (Current State)
        ffmpeg_bin = self.engine.find_ffmpeg()
        if not ffmpeg_bin or (ffmpeg_bin == "ffmpeg" and not shutil.which("ffmpeg")) or (ffmpeg_bin != "ffmpeg" and not os.path.exists(ffmpeg_bin)):
             self.view.log("오류: FFmpeg를 찾을 수 없습니다.")
             return

        # Prepare 'Job' from current state
        if not self.current_mapping or not any(self.current_mapping.values()):
            QMessageBox.warning(self.view, "오류", "유효한 파일이 없습니다!")
            return

        job = {
            "folder": self.current_folder,
            "mapping": self.current_mapping,
            "text": self.view.text_input.text(),
            "output_root": self.view.output_input.text()
        }
        
        self.run_ffmpeg_job(job, is_preview, is_queue=False)

    def run_ffmpeg_job(self, job, is_preview, is_queue):
        # Core runner
        
        # output root check
        output_folder = job['output_root'].strip()
        if not output_folder or not os.path.isdir(output_folder):
            output_folder = job['folder']
            
        # output filename
        suffix = "_preview" if is_preview else "_multiview"
        folder_name = os.path.basename(job['folder'].rstrip(os.sep))
        output_filename = f"{folder_name}{suffix}.mp4"
        
        if not is_preview:
            # Apply versioning only for render
            output_path = self.get_unique_output_path(output_folder, output_filename)
        else:
            # Overwrite preview
            output_path = os.path.join(output_folder, output_filename)

        # Get Codec Selection
        # 0 = H.265 (HEVC), 1 = H.264
        codec_idx = self.view.codec_combo.currentIndex()

        cmd = self.engine.build_command(
            job['mapping'], 
            output_path, 
            overlay_text=job['text'], 
            is_preview=is_preview,
            codec_idx=codec_idx
        )
        
        # Duration for progress
        total_duration = 0
        if is_preview:
            total_duration = 1.0
        else:
            for filepath in job['mapping'].values():
                if filepath:
                    total_duration = self.engine.get_duration(filepath)
                    if total_duration > 0: break
        
        self.view.log(f"작업 시작: {os.path.basename(output_path)}")
        self.view.log(f"저장 경로: {output_path}")
        if total_duration > 0:
             self.view.log(f"예상 소요 시간: {total_duration}초")
             
        # UI updates
        self.view.preview_btn.setEnabled(False)
        self.view.render_btn.setEnabled(False)
        self.view.add_queue_btn.setEnabled(False)
        self.view.progress_bar.setValue(0)
        
        self.worker = FFmpegWorker(cmd, total_duration, parent=self)
        self.worker.progress.connect(self.view.progress_bar.setValue)
        self.worker.conversion_finished.connect(
            lambda code, msg: self.on_process_finished(code, msg, output_path, is_queue, is_preview)
        )
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()
        
    def on_process_finished(self, code, msg, output_path, is_queue, is_preview):
        self.view.preview_btn.setEnabled(True)
        self.view.render_btn.setEnabled(True)
        self.view.add_queue_btn.setEnabled(True)
        
        if code == 0:
            self.view.progress_bar.setValue(100)
            self.view.log(f"완료! 저장 위치: {output_path}")
            
            if is_preview:
                self.view.log("프리뷰 자동 실행 중...")
                try:
                    if os.name == 'nt':
                        os.startfile(output_path)
                    else:
                        subprocess.run(["open", output_path])
                except Exception:
                    pass
            elif not is_queue:
                QMessageBox.information(self.view, "성공", f"파일 생성됨:\n{output_path}")
                
        else:
            self.view.log(f"실패: {msg}")
            self.view.progress_bar.setValue(0)
            if not is_queue:
                QMessageBox.critical(self.view, "실패", f"FFmpeg 오류:\n{msg}")

        # Queue handling
        if is_queue:
            # Remove finished job
            if self.job_queue:
                self.job_queue.pop(0) # Remove first
                self.view.queue_list.takeItem(0)
            
            if code != 0:
                # Decide policy: Stop or Continue? Usually continue or ask.
                # For now log error and continue
                self.view.log("오류 발생에도 불구하고 다음 작업으로 진행합니다.")
                
            # Trigger next
            self.process_next_job()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Setup
    view = MainWindow()
    engine = MultiviewerEngine()
    controller = AppController(view, engine)
    
    view.show()
    sys.exit(app.exec())
