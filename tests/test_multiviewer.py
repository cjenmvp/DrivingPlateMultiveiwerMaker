import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import subprocess
import tempfile
import unittest
from pathlib import Path

from ffmpeg_engine import MultiviewerEngine


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.engine = MultiviewerEngine()
        cls.prores = cls.root / "임의 이름 'A;[1],%.mov"
        cls.h264 = cls.root / '카메라 자유.mp4'
        for path, codec, fps, duration, color in [(cls.prores, 'prores_ks', '24', '0.5', 'red'),
                                                 (cls.h264, 'libx264', '30000/1001', '1', 'blue')]:
            subprocess.run([cls.engine.find_ffmpeg(), '-v', 'error', '-f', 'lavfi', '-i',
                            f'color={color}:s=160x90:r={fps}:d={duration}', '-c:v', codec,
                            '-threads', '1', str(path)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_manual_mixed_inputs_and_outputs(self):
        for codec, ext, expected in [(1, '.mp4', 'h264'), (0, '.mp4', 'hevc'),
                                     (2, '.mov', 'prores'), (3, '.mov', 'prores')]:
            with self.subTest(codec=codec):
                output = self.root / f'출력{codec}{ext}'
                command = self.engine.build_command({0: str(self.prores), 8: str(self.h264)}, str(output),
                    overlay_text="서울: O'Brien [A]; 100% \\ drive", codec_idx=codec)
                result = subprocess.run(command, capture_output=True, text=True, timeout=90)
                self.assertEqual(result.returncode, 0, result.stderr)
                info = self.engine.probe(str(output))
                self.assertEqual(info['codec'], expected)
                self.assertAlmostEqual(info['duration'], .5, delta=.06)
                # 실제 위치와 빈 슬롯을 픽셀로 확인.
                pixels = subprocess.run([self.engine.find_ffmpeg(), '-v', 'error', '-i', str(output),
                                         '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                                        check=True, capture_output=True).stdout
                def pixel(x, y):
                    pos = (y * 1920 + x) * 3
                    return pixels[pos:pos + 3]
                self.assertGreater(pixel(100, 100)[0], 150)
                self.assertLess(max(pixel(740, 100)), 15)
                self.assertGreater(pixel(1400, 800)[2], 150)

    def test_longest_and_lut(self):
        lut = self.root / "보정 'x;[a],.cube"
        lut.write_text('LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n')
        output = self.root / 'longest.mp4'
        command = self.engine.build_command({4: str(self.prores), 7: str(self.h264)}, str(output),
            codec_idx=1, duration_mode='longest', lut_mapping={4: str(lut)})
        result = subprocess.run(command, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertAlmostEqual(self.engine.get_duration(str(output)), 1, delta=.1)

    def test_scan_and_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ['random.MXF', '10_a.mov', '10_b.mp4', '12_c.mov', 'scene_multiview.mp4']:
                (root / name).touch()
            mapping = self.engine.scan_folder(folder)
            self.assertIsNone(mapping[0])
            self.assertTrue(mapping[1].endswith('12_c.mov'))
            self.assertTrue(self.engine.scan_warnings)
            mapping = self.engine.scan_folder(folder, 'sequential')
            self.assertEqual(sum(bool(p) for p in mapping.values()), 4)
            self.assertFalse(any(self.engine.scan_folder(folder, 'manual').values()))
        with self.assertRaises(ValueError):
            self.engine.build_command({}, str(self.root / 'empty.mp4'))
        with self.assertRaises(ValueError):
            self.engine.build_command({0: str(self.prores)}, str(self.prores))
        invalid = self.root / 'notvideo.dat'
        invalid.write_text('invalid')
        with self.assertRaises(ValueError):
            self.engine.probe(str(invalid))

    def test_queue_worker_and_cancel(self):
        from unittest.mock import patch
        from PySide6.QtCore import QEventLoop, QTimer
        from PySide6.QtWidgets import QApplication
        from main import AppController, FFmpegWorker
        from gui import MainWindow
        import sys
        app = QApplication.instance() or QApplication([])
        view = MainWindow()
        controller = AppController(view, self.engine)
        controller.handle_manual_assignment(0, str(self.prores))
        view.codec_combo.setCurrentIndex(2)
        controller.handle_add_queue({'text': '', 'output_root': str(self.root / 'queue')})
        view.codec_combo.setCurrentIndex(1)
        with patch('main.QMessageBox.information'):
            controller.handle_start_queue()
            loop = QEventLoop()
            timer = QTimer()
            timer.timeout.connect(lambda: loop.quit() if not controller.busy else None)
            timer.start(20)
            QTimer.singleShot(15000, loop.quit)
            loop.exec()
            timer.stop()
        self.assertFalse(controller.busy)
        self.assertFalse(controller.job_queue)
        outputs = list((self.root / 'queue').glob('*.mov'))
        self.assertEqual(len(outputs), 1)
        self.assertEqual(self.engine.probe(str(outputs[0]))['codec'], 'prores')
        self.assertEqual(view.progress_bar.value(), 100)
        worker = FFmpegWorker([sys.executable, '-c', 'import time; time.sleep(30)'])
        loop = QEventLoop()
        worker.finished.connect(loop.quit)
        worker.start()
        QTimer.singleShot(50, worker.cancel)
        QTimer.singleShot(5000, loop.quit)
        loop.exec()
        self.assertTrue(worker.wait(1000))
        self.assertEqual(worker.result_code, -2)
        view.close()

    def test_manual_gui_without_scan(self):
        from PySide6.QtWidgets import QApplication
        from main import AppController
        from gui import MainWindow
        app = QApplication.instance() or QApplication([])
        view = MainWindow()
        controller = AppController(view, self.engine)
        controller.handle_manual_assignment(8, str(self.prores))
        self.assertEqual(controller.current_folder, str(self.root))
        self.assertEqual(controller.current_mapping[8], str(self.prores))
        controller.handle_add_queue({'text': '', 'output_root': ''})
        self.assertEqual(controller.job_queue[0]['codec_idx'], 1)
        controller.handle_manual_assignment(8, '')
        self.assertFalse(controller.current_mapping[8])
        self.assertEqual(controller.job_queue[0]['mapping'][8], str(self.prores))
        controller.handle_clear()
        self.assertFalse(any(controller.current_mapping.values()))
        view.close()


if __name__ == '__main__':
    unittest.main()
