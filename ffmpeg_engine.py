"""파일명과 입력 코덱을 분리한 3×3 멀티뷰 합성 엔진."""
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import site
from fractions import Fraction

VIDEO_EXTENSIONS = ('.mp4', '.mov', '.mkv', '.avi', '.mxf', '.m4v', '.mts', '.m2ts', '.ts', '.webm', '.mpg', '.mpeg')
VIDEO_FILTER = '영상 파일 (' + ' '.join('*' + ext for ext in VIDEO_EXTENSIONS) + ');;모든 파일 (*)'


def filter_value(value):
    # 옵션 파서와 필터 그래프 파서를 차례로 통과하도록 두 단계 이스케이프.
    value = str(value)
    for chars in ("\\':", "\\'[],;"):
        value = ''.join('\\' + c if c in chars else c for c in value)
    return value


class MultiviewerEngine:
    def __init__(self):
        self.slot_patterns = {0: ['10_'], 1: ['12_'], 2: ['02_'], 3: ['09_'],
                              4: ['Top_', '13_'], 5: ['03_'], 6: ['08_'], 7: ['06_'], 8: ['04_']}
        self.scan_warnings = []
        self._probe_cache = {}
        self._binary_cache = {}

    def scan_folder(self, folder_path, mode='naming'):
        mapping = dict.fromkeys(range(9))
        self.scan_warnings = []
        if not os.path.isdir(folder_path):
            raise ValueError('존재하는 폴더를 선택하세요.')
        files = sorted((p for p in Path(folder_path).iterdir()
                        if p.is_file() and not p.name.startswith('.') and p.suffix.lower() in VIDEO_EXTENSIONS
                        and not re.search(r'_(?:multiview|preview)(?:_v\d+)?$', p.stem)),
                       key=lambda p: p.name.casefold())
        if mode == 'manual':
            return mapping
        if mode == 'sequential':
            for i, path in enumerate(files[:9]):
                mapping[i] = str(path)
            if len(files) > 9:
                self.scan_warnings.append(f'{len(files) - 9}개 파일은 9칸을 초과하여 배치하지 않았습니다.')
        else:
            used = set()
            for slot, patterns in self.slot_patterns.items():
                matches = [p for p in files if p not in used and any(
                    p.name.casefold().startswith(pattern.casefold()) or '_' + pattern.casefold() in p.name.casefold()
                    for pattern in patterns)]
                if len(matches) == 1:
                    mapping[slot] = str(matches[0])
                    used.add(matches[0])
                elif len(matches) > 1:
                    self.scan_warnings.append(f'슬롯 {slot + 1}: 후보 {len(matches)}개 — 직접 선택하세요.')
            remaining = len(files) - len(used)
            if remaining:
                self.scan_warnings.append(f'{remaining}개 파일이 자동 배치되지 않았습니다. 수동 선택 또는 파일명 순서 배치를 이용하세요.')
        return mapping

    def find_binary(self, name):
        if name in self._binary_cache:
            return self._binary_cache[name]
        configured = os.environ.get(name.upper() + '_BINARY')
        candidates = [configured] if configured else []
        candidates += [str(Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / name),
                       shutil.which(name), '/opt/homebrew/bin/' + name, '/usr/local/bin/' + name]
        # 이미 설치된 static-ffmpeg도 탐색하되 실행 중 자동 다운로드는 하지 않음.
        for base in [site.getusersitepackages(), *site.getsitepackages()]:
            candidates.extend(str(p) for p in (Path(base) / 'static_ffmpeg' / 'bin').glob('*/' + name))
        for candidate in candidates:
            if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                if name == 'ffmpeg':
                    filters = subprocess.run([candidate, '-hide_banner', '-filters'], capture_output=True,
                                             text=True, errors='replace', timeout=10)
                    if not re.search(r'\bdrawtext\b', filters.stdout):
                        if configured == candidate:
                            raise RuntimeError('지정한 FFmpeg에 drawtext 필터가 없습니다. 전체 기능 빌드를 사용하세요.')
                        continue
                self._binary_cache[name] = candidate
                return candidate
        raise RuntimeError(f'{name} 실행 파일이 없습니다. FFmpeg를 설치하거나 {name.upper()}_BINARY를 지정하세요.')

    def find_ffmpeg(self):
        return self.find_binary('ffmpeg')

    def find_ffprobe(self):
        return self.find_binary('ffprobe')

    def probe(self, path):
        path = os.path.abspath(path)  # 실제 파일명의 유니코드 표현을 변경하지 않음.
        stat = os.stat(path)
        key = (path, stat.st_mtime_ns, stat.st_size)
        if key in self._probe_cache:
            return self._probe_cache[key]
        result = subprocess.run([self.find_ffprobe(), '-v', 'error', '-select_streams', 'v:0',
                                 '-show_streams', '-show_format', '-of', 'json', path],
                                capture_output=True, text=True, errors='replace', timeout=30)
        if result.returncode:
            raise ValueError(f'영상을 읽을 수 없습니다: {path}\n{result.stderr[-1500:]}')
        data = json.loads(result.stdout)
        streams = data.get('streams', [])
        if not streams or streams[0].get('disposition', {}).get('attached_pic'):
            raise ValueError(f'영상 스트림이 없습니다: {path}')
        stream = streams[0]
        duration = 0
        for raw in (stream.get('duration'), data.get('format', {}).get('duration')):
            try:
                duration = float(raw)
                if math.isfinite(duration) and duration > 0:
                    break
            except (TypeError, ValueError):
                pass
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError(f'영상 길이를 확인할 수 없습니다: {path}')
        fps = Fraction(30)
        for raw in (stream.get('avg_frame_rate'), stream.get('r_frame_rate')):
            try:
                candidate = Fraction(raw)
                if 0 < candidate <= 240:
                    fps = candidate
                    break
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        info = dict(duration=duration, fps=str(fps), codec=stream.get('codec_name', 'unknown'))
        self._probe_cache[key] = info
        return info

    def get_duration(self, path):
        return self.probe(path)['duration']

    def get_fps(self, path):
        return float(Fraction(self.probe(path)['fps']))

    def build_command(self, file_mapping, output_path, overlay_text='', is_preview=False,
                      codec_idx=0, lut_mapping=None, duration_mode='shortest'):
        paths = {i: os.path.abspath(p) for i, p in file_mapping.items() if p and i in range(9)}
        if not paths:
            raise ValueError('최소 한 개의 영상을 슬롯에 지정하세요.')
        output_path = os.path.abspath(output_path)
        if any(os.path.realpath(p) == os.path.realpath(output_path) for p in paths.values()):
            raise ValueError('출력 경로는 입력 영상과 달라야 합니다.')
        metadata = {i: self.probe(p) for i, p in paths.items()}
        fps = metadata[min(metadata)]['fps']
        durations = [info['duration'] for info in metadata.values()]
        duration = max(durations) if duration_mode == 'longest' else min(durations)
        if is_preview:
            duration = min(1, duration)
        cmd = [self.find_ffmpeg(), '-hide_banner', '-nostdin', '-n', '-filter_complex_threads', '2']
        filters = []
        for input_idx, (slot, path) in enumerate(sorted(paths.items())):
            cmd += ['-threads', '2', '-i', path]
            lut = (lut_mapping or {}).get(slot)
            if lut and not os.path.isfile(lut):
                raise ValueError(f'LUT 파일이 없습니다: {lut}')
            lut_filter = 'lut3d=file=' + filter_value(os.path.abspath(lut)) + ',' if lut else ''
            filters.append(f'[{input_idx}:v:0]setpts=PTS-STARTPTS,{lut_filter}'
                           f'scale=640:360:force_original_aspect_ratio=decrease:force_divisible_by=2,'
                           f'pad=640:360:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},'
                           f'format=yuv422p10le,tpad=stop_mode=clone:stop_duration={duration},'
                           f'trim=duration={duration},settb=AVTB[v{slot}]')
        for slot in range(9):
            if slot not in paths:
                filters.append(f'color=c=black:s=640x360:r={fps}:d={duration},'
                               f'format=yuv422p10le,settb=AVTB[v{slot}]')
        layout = '|'.join(f'{i % 3 * 640}_{i // 3 * 360}' for i in range(9))
        filters.append(''.join(f'[v{i}]' for i in range(9)) + f'xstack=inputs=9:layout={layout}:shortest=1[stacked]')
        output_tag = 'stacked'
        if overlay_text:
            font = next((p for p in ['/System/Library/Fonts/Supplemental/AppleGothic.ttf',
                                     '/System/Library/Fonts/AppleSDGothicNeo.ttc',
                                     'C:/Windows/Fonts/malgun.ttf'] if os.path.isfile(p)), None)
            font_opt = 'fontfile=' + filter_value(font) + ':' if font else ''
            filters.append(f'[stacked]drawtext={font_opt}text={filter_value(overlay_text)}:expansion=none:'
                           'fontcolor=white:fontsize=48:x=(w-text_w)/2:y=h-80:box=1:boxcolor=black@0.5[out]')
            output_tag = 'out'
        cmd += ['-filter_complex', ';'.join(filters), '-map', f'[{output_tag}]', '-an', '-t', str(duration)]
        if codec_idx in (2, 3):
            if Path(output_path).suffix.lower() != '.mov':
                raise ValueError('ProRes 출력은 .mov 확장자를 사용하세요.')
            cmd += ['-c:v', 'prores_ks', '-profile:v', '3' if codec_idx == 3 else '2', '-pix_fmt', 'yuv422p10le']
        elif codec_idx == 0:
            cmd += ['-c:v', 'libx265', '-preset', 'fast', '-crf', '23', '-pix_fmt', 'yuv420p', '-tag:v', 'hvc1']
        elif codec_idx == 1:
            cmd += ['-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p']
        else:
            raise ValueError('지원하지 않는 출력 코덱입니다.')
        cmd += ['-threads', '2', '-movflags', '+faststart', '-progress', 'pipe:1', '-nostats', output_path]
        return cmd
