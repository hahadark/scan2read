"""Stage a self-contained Windows runtime from the tested development environment."""
from pathlib import Path
import json
import shutil
import sys
import zipfile
import argparse

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'dist' / 'Scan2Read'
ONLINE_DEST = ROOT / 'build' / 'online-payload-root'


def launcher_source() -> Path:
    """Prefer the latest PyInstaller output; retain the legacy staging fallback."""
    current = ROOT / 'dist' / 'Scan2Read'
    return current if (current / 'Scan2Read.exe').is_file() else ROOT / 'build' / 'launcher' / 'Scan2Read'


def copy(source: Path, target: Path) -> None:
    shutil.copytree(source, target, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.git'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repack', action='store_true')
    parser.add_argument('--online', action='store_true',
                        help='Build the small payload whose OCR dependencies are downloaded by the installer')
    args = parser.parse_args()
    if args.online:
        stage_online_payload()
        return
    if args.repack:
        copy(launcher_source(), DEST)
        copy(ROOT / 'src' / 'scan2read', DEST / 'app' / 'scan2read')
        pack(DEST, ROOT / 'build' / 'payload.zip')
        return
    if not (DEST / 'Scan2Read.exe').exists():
        raise RuntimeError('Build the GUI launcher first')
    copy_runtime_base(DEST)
    site = ROOT / '.tools' / 'paddle-env' / 'Lib' / 'site-packages'
    shutil.copytree(site, DEST / 'runtime' / 'Lib' / 'site-packages', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '__editable__*'))
    copy(ROOT / 'src' / 'scan2read', DEST / 'app' / 'scan2read')
    copy(ROOT / '.tools' / 'epubcheck-5.3.0', DEST / 'epubcheck')
    copy(next((ROOT / '.tools' / 'jre').glob('*-jre')), DEST / 'java')
    for name in ('PP-OCRv5_mobile_det', 'korean_PP-OCRv5_mobile_rec'):
        copy(Path.home() / '.paddlex' / 'official_models' / name, DEST / 'models' / name)
    shutil.copy2(ROOT / 'docs' / 'WINDOWS.md', DEST / '사용안내.txt')
    pack(DEST, ROOT / 'build' / 'payload.zip')


def copy_runtime_base(destination: Path) -> None:
    base = Path(sys.base_prefix)
    runtime = destination / 'runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    for name in ('python.exe', 'pythonw.exe', 'python312.dll', 'python3.dll',
                 'vcruntime140.dll', 'vcruntime140_1.dll', 'LICENSE.txt'):
        shutil.copy2(base / name, runtime / name)
    copy(base / 'DLLs', runtime / 'DLLs')
    shutil.copytree(base / 'Lib', runtime / 'Lib', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('site-packages', '__pycache__', '*.pyc'))
    site = runtime / 'Lib' / 'site-packages'
    site.mkdir(parents=True, exist_ok=True)
    # ZIP archives omit empty directories; keep this so ensurepip has a
    # writable installation target after the base payload is extracted.
    (site / '.keep').touch()


def stage_online_payload() -> None:
    """Stage a small base; the installer downloads Python OCR dependencies."""
    if ONLINE_DEST.exists():
        shutil.rmtree(ONLINE_DEST)
    ONLINE_DEST.mkdir(parents=True)
    copy(launcher_source(), ONLINE_DEST)
    copy_runtime_base(ONLINE_DEST)
    copy(ROOT / 'src' / 'scan2read', ONLINE_DEST / 'app' / 'scan2read')
    copy(ROOT / '.tools' / 'epubcheck-5.3.0', ONLINE_DEST / 'epubcheck')
    copy(next((ROOT / '.tools' / 'jre').glob('*-jre')), ONLINE_DEST / 'java')
    shutil.copy2(ROOT / 'docs' / 'WINDOWS.md', ONLINE_DEST / '사용안내.txt')
    pack(ONLINE_DEST, ROOT / 'build' / 'payload-online.zip')


def pack(destination: Path, output: Path):
    files = sorted(p.relative_to(destination).as_posix() for p in destination.rglob('*') if p.is_file())
    (destination / 'installed-files.json').write_text(json.dumps(files, ensure_ascii=False), encoding='utf-8')
    temporary = output.with_suffix('.pending.zip')
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for path in destination.rglob('*'):
            if path.is_file():
                archive.write(path, path.relative_to(destination).as_posix())
    temporary.replace(output)
    print(f'Payload ready: {output}', flush=True)


if __name__ == '__main__':
    main()
