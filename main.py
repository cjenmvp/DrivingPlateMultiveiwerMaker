import sys
import os
import subprocess
import re
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QThread, Signal, QObject

from gui import MainWindow, LutConfigDialog
from ffmpeg_engine import MultiviewerEngine

class FFmpegWorker(QThread):
    progress = Signal(int)      # percentage 0-100
    
    def __init__(self, command, total_duration=0, parent=None):
        super().__init__(parent)
        self.command = command
        self.total_duration = total_duration
        
    def cancel(self):
        self.requestInterruption()
        process = getattr(self, "process", None)
        if process and process.poll() is None:
            process.kill()

    def run(self):
        from collections import deque
        tail = deque(maxlen=80)
        try:
            self.process = subprocess.Popen(self.command, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True, errors="replace",
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if self.isInterruptionRequested():
                self.process.kill()
            for line in self.process.stdout:
                tail.append(line)
                if line.startswith("out_time_us=") and self.total_duration > 0:
                    try:
                        self.progress.emit(min(99, int(int(line.split("=", 1)[1]) / 1000000 / self.total_duration * 100)))
                    except ValueError:
                        pass
            code = self.process.wait()
            self.process.stdout.close()
            self.result_code = -2 if self.isInterruptionRequested() else code
            self.result_message = "작업이 취소되었습니다." if self.isInterruptionRequested() else "".join(tail)
        except Exception as exc:
            self.result_code, self.result_message = -1, str(exc)
        finally:
            process = getattr(self, "process", None)
            if process and process.poll() is None:
                process.kill()
                process.wait()

class AppController(QObject):
    def __init__(self, view, engine):
        super().__init__()
        self.view = view
        self.engine = engine
        
        self.current_mapping = {}
        self.current_folder = ""
        self.current_luts = {} # {slot_idx: lut_path}
        
        # Queue System
        self.job_queue = [] # List of dicts
        self.is_queue_running = False
        self.busy = False
        
        self.view.request_files.connect(self.handle_files)
        self.view.request_clear.connect(self.handle_clear)
        self.view.request_cancel.connect(self.handle_cancel)
        # Connect Signals
        self.view.request_scan.connect(self.handle_scan)
        self.view.request_preview.connect(self.handle_preview)
        self.view.request_render.connect(self.handle_render)
        self.view.request_add_queue.connect(self.handle_add_queue)
        self.view.request_start_queue.connect(self.handle_start_queue)
        self.view.request_remove_queue.connect(self.handle_remove_queue)
        self.view.request_lut_settings.connect(self.handle_lut_settings)
        
        # Connect Drag & Drop Signal
        self.view.queue_list.folders_dropped.connect(self.handle_dropped_folders)
        
        # Connect Slot Manual Override
        for slot in self.view.slots:
            slot.file_changed.connect(self.handle_manual_assignment)
        
    def get_short_lut_name(self, full_name):
        """
        Convert long LUT names/keywords into shorter abbreviations.
        """
        if not full_name:
            return ""
            
        # Common mapping for abbreviations
        mapping = {
            "Panasonic": "PAN",
            "Sony": "SNY",
            "V-Log": "VLG",
            "VLog": "VLG",
            "S-Log3": "SLG3",
            "SLog3": "SLG3",
            "Rec.709": "709",
            "Rec709": "709",
            "Arri": "ARI",
            "LogC": "LGC",
            "Cine": "CNE",
            "Standard": "STD",
            "Neutral": "NTRL"
        }
        
        short_name = full_name
        for key, val in mapping.items():
            # Case insensitive replacement
            pattern = re.compile(re.escape(key), re.IGNORECASE)
            short_name = pattern.sub(val, short_name)
            
        return short_name

    def handle_cancel(self):
        if self.busy:
            self.worker.cancel()

    def handle_clear(self):
        self.current_mapping = dict.fromkeys(range(9))
        self.current_folder = ""
        self.view.path_input.clear()
        self.view.update_slots(self.current_mapping)

    def handle_files(self, paths):
        empty = [i for i in range(9) if not self.current_mapping.get(i)]
        for slot, path in zip(empty, paths):
            self.handle_manual_assignment(slot, path)
        if len(paths) > len(empty):
            self.view.log(f"빈 슬롯을 초과한 {len(paths) - len(empty)}개 파일은 추가하지 않았습니다.")

    def handle_manual_assignment(self, slot_idx, filepath):
        if filepath:
            try:
                info = self.engine.probe(filepath)
            except Exception as exc:
                self.view.log(f"파일 추가 실패: {exc}")
                return
            if not self.current_folder:
                self.current_folder = os.path.dirname(os.path.abspath(filepath))
            self.view.log(f"슬롯 {slot_idx + 1}: {os.path.basename(filepath)} / {info['codec']} / {info['duration']:.2f}초")
        self.current_mapping[slot_idx] = filepath or None
        self.view.update_slots(self.current_mapping)

    def handle_lut_settings(self):
        # Allow LUT settings without scanning first
        dlg = LutConfigDialog(self.view, self.current_mapping, self.current_luts)
        if dlg.exec():
            # Save new mapping
            self.current_luts = dlg.get_mapping()
            # Count set LUTs
            count = len(self.current_luts)
            if count > 0:
                self.view.log(f"LUT 설정됨: {count}개 슬롯에 적용")
            else:
                self.view.log("LUT 설정 초기화 (모두 해제)")

            # Also update pending jobs in queue
            updated_count = 0
            for job in self.job_queue:
                if job['status'] == "Ready":
                    job['lut_mapping'] = self.current_luts.copy()
                    updated_count += 1
            
            if updated_count > 0:
                self.view.log(f"대기중인 {updated_count}개 작업에도 LUT 설정이 적용되었습니다.")

    def handle_scan(self, folder_path):
        self.view.log(f"스캔 중: {folder_path}")
        try:
            mapping = self.engine.scan_folder(folder_path, self.view.scan_mode.currentData())
        except Exception as exc:
            self.view.log(f"스캔 실패: {exc}")
            return
        self.current_folder = folder_path
        self.current_mapping = mapping
        for warning in self.engine.scan_warnings:
            self.view.log(warning)
        self.view.update_slots(self.current_mapping)
        self.view.log("스캔 완료.")

    def handle_preview(self):
        self.run_ffmpeg(is_preview=True)

    def handle_render(self):
        self.run_ffmpeg(is_preview=False)

    def handle_dropped_folders(self, folders):
        for folder in folders:
            # 1. Scan the dropped folder
            try:
                mapping = self.engine.scan_folder(folder, self.view.scan_mode.currentData())
                for warning in self.engine.scan_warnings:
                    self.view.log(warning)
            except Exception as exc:
                self.view.log(f"스캔 실패: {exc}")
                continue
            
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
                "lut_mapping": self.current_luts.copy(),
                "codec_idx": self.view.codec_combo.currentIndex(),
                "duration_mode": self.view.duration_combo.currentData(),
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
            "lut_mapping": self.current_luts.copy(),
            "codec_idx": self.view.codec_combo.currentIndex(),
            "duration_mode": self.view.duration_combo.currentData(),
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
            
        if self.is_queue_running or self.busy:
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
            QMessageBox.information(self.view, "완료", "대기열 처리가 끝났습니다. 작업별 성공 여부는 로그를 확인하세요.")
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
        if self.busy:
            return

        # Prepare 'Job' from current state
        if not self.current_mapping or not any(self.current_mapping.values()):
            QMessageBox.warning(self.view, "오류", "유효한 파일이 없습니다!")
            return

        job = {
            "folder": self.current_folder,
            "mapping": self.current_mapping,
            "text": self.view.text_input.text(),
            "output_root": self.view.output_input.text(),
            "lut_mapping": self.current_luts
        }
        
        self.run_ffmpeg_job(job, is_preview, is_queue=False)

    def run_ffmpeg_job(self, job, is_preview, is_queue):
        if self.busy:
            return
        try:
            self.start_ffmpeg_job(job, is_preview, is_queue)
        except Exception as exc:
            self.view.log(f"작업 준비 실패: {exc}")
            self.is_queue_running = False
            self.set_busy(False)

    def set_busy(self, busy):
        self.busy = busy
        for widget in (self.view.preview_btn, self.view.render_btn, self.view.add_queue_btn,
                       self.view.btn_queue_start, self.view.btn_queue_remove, self.view.queue_list,
                       self.view.browse_btn, self.view.path_input, self.view.rescan_btn, self.view.files_btn,
                       self.view.clear_btn, self.view.lut_btn, *self.view.slots):
            widget.setEnabled(not busy)
        self.view.cancel_btn.setEnabled(busy)

    def start_ffmpeg_job(self, job, is_preview, is_queue):
        # Core runner
        
        first_input = next(p for p in job['mapping'].values() if p)
        source_folder = job.get('folder') or os.path.dirname(os.path.abspath(first_input))
        output_folder = job['output_root'].strip() or source_folder
        os.makedirs(output_folder, exist_ok=True)
        suffix = "_preview" if is_preview else "_multiview"
        folder_name = os.path.basename(source_folder.rstrip(os.sep)) or "manual"
        codec_idx = job.get('codec_idx', self.view.codec_combo.currentIndex())
        extension = '.mov' if codec_idx in (2, 3) else '.mp4'
        output_path = self.get_unique_output_path(output_folder, f"{folder_name}{suffix}{extension}")
        lut_mapping = job.get('lut_mapping', {})

        # Update Overlay Text
        overlay_text = job['text']

        cmd = self.engine.build_command(
            job['mapping'], 
            output_path, 
            overlay_text=overlay_text, 
            is_preview=is_preview,
            codec_idx=codec_idx,
            lut_mapping=lut_mapping,
            duration_mode=job.get("duration_mode", self.view.duration_combo.currentData())
        )
        
        total_duration = float(cmd[cmd.index('-t') + 1])

        self.view.log(f"작업 시작: {os.path.basename(output_path)}")
        self.view.log(f"저장 경로: {output_path}")

        if total_duration > 0:
             self.view.log(f"출력 영상 길이: {total_duration}초")
             
        self.set_busy(True)
        self.view.progress_bar.setValue(0)
        self.worker = FFmpegWorker(cmd, total_duration, parent=self)
        worker = self.worker
        worker.progress.connect(self.view.progress_bar.setValue)
        worker.finished.connect(lambda: self.on_process_finished(
            worker.result_code, worker.result_message, output_path, is_queue, is_preview))
        worker.finished.connect(worker.deleteLater)
        self.worker.start()
        
    def on_process_finished(self, code, msg, output_path, is_queue, is_preview):
        self.set_busy(False)
        if code == -2:
            self.is_queue_running = False
            self.view.progress_bar.setValue(0)
            self.view.log(f"작업 취소됨. 대기열은 유지했습니다. 미완성 파일이 있을 수 있습니다: {output_path}")
            return

        if code == 0:
            self.view.progress_bar.setValue(100)
            self.view.log(f"완료! 저장 위치: {output_path}")
            
            if is_preview:
                self.view.log("프리뷰 자동 실행 중...")
                try:
                    if os.name == 'nt':
                        os.startfile(output_path)
                    else:
                        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", output_path])
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
