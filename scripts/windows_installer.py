"""Standalone, per-user installer. No privileged helper is required."""
import argparse
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import zipfile


CPU_INDEX_URL = 'https://www.paddlepaddle.org.cn/packages/stable/cpu/'
RUNTIME_PACKAGES = (
    'paddlepaddle==3.3.1',
    'paddleocr==3.7.0',
    'pypdfium2==5.13.0',
    'Pillow==12.3.0',
    'kiwipiepy==0.23.2',
)
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0


def payload_path() -> Path:
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).parent.parent / 'build'))
    for name in ('payload-online.zip', 'payload.zip'):
        candidate = root / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError('설치 데이터(payload-online.zip)를 찾을 수 없습니다.')


def run_step(command: list[str], status, env: dict[str, str] | None = None) -> None:
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding='utf-8', errors='replace', env=env,
                               creationflags=_NO_WINDOW)
    recent = []
    for line in process.stdout:
        line = line.strip()
        if line:
            recent.append(line)
            recent = recent[-4:]
            status(line)
    code = process.wait()
    if code:
        detail = recent[-1] if recent else f'종료 코드 {code}'
        raise RuntimeError(f'구성요소 설치 실패: {detail}')


def install_runtime_dependencies(target: Path, progress=lambda value: None,
                                 status=lambda text: None) -> None:
    python = target / 'runtime' / 'python.exe'
    status('설치 도구를 준비하는 중…')
    run_step([str(python), '-m', 'ensurepip', '--upgrade'], status)
    progress(20)
    status('OCR·문맥 보정 구성요소를 다운로드하고 설치하는 중…')
    run_step([str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
              *RUNTIME_PACKAGES, '--extra-index-url', CPU_INDEX_URL], status)
    progress(88)
    status('한국어 OCR 모델을 다운로드하는 중…')
    env = os.environ.copy()
    env['PYTHONPATH'] = str(target / 'app')
    env['PYTHONUTF8'] = '1'
    env['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
    script = ('from scan2read.ocr.paddle import PaddleEngine; '
              'engine=PaddleEngine(device="cpu"); engine.cache_identity()')
    run_step([str(python), '-c', script], status, env)
    progress(95)


def write_install_manifest(target: Path) -> None:
    excluded = {'installed-files.json', 'uninstall.ps1'}
    files = sorted(path.relative_to(target).as_posix() for path in target.rglob('*')
                   if path.is_file() and path.name not in excluded)
    (target / 'installed-files.json').write_text(
        json.dumps(files, ensure_ascii=False), encoding='utf-8')


def install(target: Path, progress=lambda value: None, status=lambda text: None,
            shortcuts=True, download=True):
    target = target.resolve()
    if target.exists() and any(target.iterdir()):
        raise ValueError('설치 폴더가 비어 있지 않습니다. 빈 폴더를 선택하세요.')
    clean_on_failure = not target.exists() or not any(target.iterdir())
    try:
        status('기본 프로그램 파일을 푸는 중…')
        with zipfile.ZipFile(payload_path()) as archive:
            entries = archive.infolist()
            for entry in entries:
                path = (target / entry.filename).resolve()
                if not path.is_relative_to(target):
                    raise ValueError('Invalid archive path')
            target.mkdir(parents=True, exist_ok=True)
            for index, entry in enumerate(entries):
                archive.extract(entry, target)
                if index % 100 == 0:
                    progress(index / max(1, len(entries)) * 15)
        if download:
            install_runtime_dependencies(target, progress, status)
    except Exception:
        if clean_on_failure and target.exists():
            shutil.rmtree(target, ignore_errors=True)
        raise
    if shortcuts:
        # Pass paths via environment, never interpolate them into shell code.
        env = os.environ.copy()
        env['SCAN2READ_INSTALL'] = str(target)
        script = '''$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Programs')) 'Scan2Read.lnk'))
$link.TargetPath = Join-Path $env:SCAN2READ_INSTALL 'Scan2Read.exe'
$link.WorkingDirectory = $env:SCAN2READ_INSTALL
$link.Save()
'''
        subprocess.run(['powershell.exe', '-NoProfile', '-Command', script], env=env,
                       check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Uninstall\Scan2Read') as key:
            for name, value in {'DisplayName': 'Scan2Read', 'DisplayVersion': '0.1.0',
                                'InstallLocation': str(target),
                                'UninstallString': 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + str(target / 'uninstall.ps1') + '"'}.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    uninstall = r'''Add-Type -AssemblyName PresentationFramework
if ([System.Windows.MessageBox]::Show('Scan2Read를 제거할까요? OCR 캐시와 EPUB은 보존합니다.', 'Scan2Read', 'YesNo') -ne 'Yes') { exit }
$installRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$manifest = Join-Path $installRoot 'installed-files.json'
$files = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($file in $files) {
    $resolved = [IO.Path]::GetFullPath((Join-Path $installRoot $file))
    if (-not $resolved.StartsWith($installRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid file path' }
    if (Test-Path -LiteralPath $resolved -PathType Leaf) { Remove-Item -LiteralPath $resolved -ErrorAction Stop }
}
Remove-Item -LiteralPath $manifest -ErrorAction Stop
$shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'Scan2Read.lnk'
if (Test-Path -LiteralPath $shortcut) {
    $shell = New-Object -ComObject WScript.Shell
    if ($shell.CreateShortcut($shortcut).TargetPath -eq (Join-Path $installRoot 'Scan2Read.exe')) { Remove-Item -LiteralPath $shortcut }
}
Remove-Item -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Scan2Read' -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $PSCommandPath
Get-ChildItem -LiteralPath $installRoot -Directory -Recurse | Sort-Object FullName -Descending | ForEach-Object {
    if (-not (Get-ChildItem -LiteralPath $_.FullName -Force | Select-Object -First 1)) { Remove-Item -LiteralPath $_.FullName }
}
if (-not (Get-ChildItem -LiteralPath $installRoot -Force | Select-Object -First 1)) { Remove-Item -LiteralPath $installRoot }
'''
    (target / 'uninstall.ps1').write_text(uninstall, encoding='utf-8-sig')
    write_install_manifest(target)
    progress(100)
    status('설치가 완료되었습니다.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test-install', type=Path, help='Extract to an empty test folder without registration')
    parser.add_argument('--skip-download', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.test_install:
        install(args.test_install, shortcuts=False, download=not args.skip_download)
        return
    window = tk.Tk()
    window.title('Scan2Read 설치')
    window.geometry('650x340')
    window.resizable(False, False)
    frame = ttk.Frame(window, padding=24)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Scan2Read 설치', font=('맑은 고딕', 20, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='PDF를 듣는 책으로 · 설치 중 OCR 구성요소 다운로드', padding=(0,8,0,20)).pack(anchor='w')
    destination = tk.StringVar(value=str(Path(os.environ['LOCALAPPDATA']) / 'Programs' / 'Scan2Read'))
    ttk.Entry(frame, textvariable=destination).pack(fill='x')
    def browse():
        path = filedialog.askdirectory()
        if path: destination.set(str(Path(path) / 'Scan2Read'))
    browse_button = ttk.Button(frame, text='설치 위치 선택', command=browse)
    browse_button.pack(anchor='e', pady=8)
    bar = ttk.Progressbar(frame)
    bar.pack(fill='x')
    status = tk.StringVar(value='인터넷 연결이 필요합니다. 다운로드 약 250MB, 설치 후 약 1GB입니다.')
    ttk.Label(frame, textvariable=status, wraplength=590).pack(anchor='w', pady=8)
    events = queue.Queue()
    active = False
    def start():
        nonlocal active
        active = True
        button.configure(state='disabled'); browse_button.configure(state='disabled')
        target = Path(destination.get())
        def worker():
            try:
                install(target, lambda n: events.put(('progress', n)),
                        lambda text: events.put(('status', text)))
                events.put(('done', target))
            except Exception as exc: events.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()
    def poll():
        nonlocal active
        while not events.empty():
            kind, value = events.get()
            if kind == 'progress': bar['value'] = value; status.set(f'설치 파일 복사 중… {value:.0f}%')
            elif kind == 'status': status.set(value)
            elif kind == 'done':
                active = False; status.set('설치 완료. 시작 메뉴에서 Scan2Read를 실행하세요.')
                button.configure(text='Scan2Read 실행', state='normal', command=lambda: os.startfile(value / 'Scan2Read.exe'))
            else:
                active = False; status.set('설치 실패'); messagebox.showerror('설치 오류', value)
                button.configure(state='normal'); browse_button.configure(state='normal')
        window.after(100, poll)
    button = ttk.Button(frame, text='설치', command=start)
    button.pack(anchor='e')
    window.protocol('WM_DELETE_WINDOW', lambda: None if active else window.destroy())
    window.after(100, poll)
    window.mainloop()


if __name__ == '__main__':
    main()
