"""합성 샘플로 CPU/Apple 하드웨어 처리 시간을 측정합니다. 원본 파일은 변경하지 않습니다."""
import argparse
import importlib.util
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ffmpeg_engine import MultiviewerEngine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference-ref', help='비교할 이전 엔진의 Git 커밋')
    parser.add_argument('--report', default='benchmark-results.json')
    parser.add_argument('--duration', type=int, default=3)
    parser.add_argument('--repeat', type=int, default=2)
    args = parser.parse_args()
    engine = MultiviewerEngine()
    results = []
    with tempfile.TemporaryDirectory(prefix='multiview-benchmark-') as folder:
        root = Path(folder)
        baseline = None
        if args.reference_ref:
            source = subprocess.run(['git', 'show', args.reference_ref + ':ffmpeg_engine.py'],
                                    capture_output=True, text=True, check=True).stdout
            module_file = root / 'baseline.py'
            module_file.write_text(source)
            spec = importlib.util.spec_from_file_location('baseline', module_file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            baseline = module.MultiviewerEngine()
        inputs = []
        for codec, ext in [('prores_ks', '.mov'), ('libx264', '.mp4')]:
            path = root / (codec + ext)
            subprocess.run([engine.find_ffmpeg(), '-v', 'error', '-f', 'lavfi', '-i',
                            f'testsrc2=s=1920x1080:r=30:d={args.duration}',
                            '-c:v', codec, '-threads', '4', str(path)], check=True)
            inputs.append(str(path))
        mapping = {i: inputs[i % 2] for i in range(9)}
        for codec_idx in (1, 0, 2):
            for mode in (['baseline'] if baseline else []) + ['cpu', 'hardware']:
                active = baseline if mode == 'baseline' else engine
                if mode == 'hardware' and not engine.hardware_encoder(codec_idx):
                    results.append({'codec': codec_idx, 'mode': mode, 'unavailable': True})
                    continue
                samples = []
                for repeat in range(args.repeat):
                    output = root / f'{codec_idx}-{mode}-{repeat}{".mov" if codec_idx == 2 else ".mp4"}'
                    options = {} if mode == 'baseline' else {'acceleration': mode}
                    cmd = active.build_command(mapping, str(output), codec_idx=codec_idx, **options)
                    start = time.perf_counter()
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                    if result.returncode:
                        raise RuntimeError(result.stderr[-3000:])
                    samples.append(round(time.perf_counter() - start, 3))
                    output.unlink()
                record = {'codec': codec_idx, 'mode': mode, 'seconds': samples,
                          'median_seconds': statistics.median(samples)}
                results.append(record)
                print(json.dumps(record), flush=True)
    report = {'sample': f'9 slots, alternating ProRes/H.264 1080p30, {args.duration}s, no LUT, synthetic testsrc2',
              'note': 'Default encoder quality/bitrate differs by backend; this is a workflow timing comparison, not equal-quality compression testing.',
              'results': results}
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
