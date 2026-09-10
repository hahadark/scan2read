"""Small local conversion UI; heavy OCR runs in a separate process."""
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox
from scan2read.project.batch import Preferences, plan_outputs
from scan2read.project.credentials import load_api_key, save_api_key
from scan2read.cleanup.ai_providers import default_model, models_for, resolve_model
from scan2read.cleanup.ai_usage import FEATURE_LABELS, estimate_book_usage

_PROVIDER_LABELS = {"openai": "OpenAI", "anthropic": "Claude (Anthropic)", "google": "Gemini (Google)"}
_PROVIDER_NAMES = {label: key for key, label in _PROVIDER_LABELS.items()}
_PROVIDER_ENV_VAR = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "google": "GOOGLE_API_KEY"}

# A chunk shorter than this isn't worth splitting off into its own process --
# each one pays a fixed PaddleOCR model-load cost regardless of how many
# pages it does. Used to cap how many pieces a book's page range is cut into.
MIN_CHUNK_PAGES = 15

_PAGE_PROGRESS = re.compile(r"(?:Rendering/OCR|Cached OCR|Text layer): (\d+) / (\d+)")

try:
    from tkinterdnd2 import DND_FILES
except ImportError:
    DND_FILES = None

try:
    import sv_ttk
except ImportError:
    sv_ttk = None

# sv_ttk's own sv.tcl creates these named Tcl fonts using "Segoe UI Variable",
# a Windows 11 font whose Hangul fallback isn't reliable on every machine --
# it rendered visibly wrong on the user's own PC. Overriding them to Malgun
# Gothic (Windows' standard Korean UI font) keeps sv_ttk's flat styling and
# sizes but fixes Hangul rendering everywhere sv_ttk assigns its own font
# (Treeview rows/headings, LabelFrame captions).
_SV_TTK_BOLD_FONTS = {"SunValleyBodyStrongFont", "SunValleySubtitleFont", "SunValleyTitleFont",
                      "SunValleyTitleLargeFont", "SunValleyDisplayFont"}
_SV_TTK_FONTS = ["SunValleyCaptionFont", "SunValleyBodyFont", *_SV_TTK_BOLD_FONTS]


def _use_malgun_gothic(window: tk.Tk) -> None:
    for name in _SV_TTK_FONTS:
        try:
            font = tkfont.Font(root=window, name=name, exists=True)
        except tk.TclError:
            continue
        font.configure(family="맑은 고딕", weight="bold" if name in _SV_TTK_BOLD_FONTS else "normal")


def dpi_scale() -> float:
    """Windows' current display scale factor (1.0 at 100%, 1.5 at 150%, ...).

    Must run before any Tk window is created: it also opts the process into
    Windows' own DPI awareness, which stops Windows from covering for an
    unaware process by stretching a 100%-rendered bitmap (blurry) --
    unaware is the PyInstaller-built exe's default, since it carries no
    manifest declaring otherwise. Returns 1.0 on non-Windows or on any
    failure, which leaves every caller's math a no-op.
    """
    if os.name != "nt":
        return 1.0
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()  # older Windows fallback
        return ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100
    except (AttributeError, OSError, ValueError):
        return 1.0


def app_root() -> Path:
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parents[2]
    executable_root = Path(sys.executable).parent
    # Installed copies keep runtime/ beside the launcher.  A launcher run
    # directly from PyInstaller's build/dist tree instead uses the repository's
    # tested development environment two levels above it.
    for candidate in (executable_root, executable_root.parent, executable_root.parent.parent):
        if ((candidate / "runtime" / "python.exe").is_file() or
                (candidate / ".tools" / "paddle-env" / "Scripts" / "python.exe").is_file()):
            return candidate
    return executable_root


_DROP_TOKEN = re.compile(r"\{([^{}]*)\}|(\S+)")


def parse_dropped_paths(data: str) -> list[str]:
    """Split a tkinterdnd2 <<Drop>> payload without Tcl backslash substitution.

    tk.splitlist() would treat a bare (unbraced) Windows path's backslashes as
    escape sequences (e.g. "\\t" becomes a tab), corrupting the path. Every
    brace-quoted or whitespace-separated token is instead taken verbatim.
    """
    return [brace or bare for brace, bare in _DROP_TOKEN.findall(data)]


def pdfs_from_inputs(paths: list[str]) -> list[str]:
    """Expand dropped PDF files and the PDFs directly inside dropped folders."""
    pdfs: list[Path] = []
    for value in paths:
        path = Path(value)
        try:
            if path.is_file() and path.suffix.lower() == ".pdf":
                pdfs.append(path)
            elif path.is_dir():
                pdfs.extend(sorted(
                    (child for child in path.iterdir()
                     if child.is_file() and child.suffix.lower() == ".pdf"),
                    key=lambda child: child.name.casefold(),
                ))
        except OSError:
            continue
    return [str(path.resolve()) for path in pdfs]


def _plan_chunks(start: int, end: int, max_parallel: int) -> list[tuple[int, int]]:
    """Split [start, end] into up to `max_parallel` contiguous page ranges,
    never smaller than MIN_CHUNK_PAGES. Returns a single range covering the
    whole span when splitting wouldn't help (max_parallel==1 or too few pages)."""
    total = end - start + 1
    num_chunks = max(1, min(max_parallel, total // MIN_CHUNK_PAGES))
    if num_chunks <= 1:
        return [(start, end)]
    chunk_size = -(-total // num_chunks)  # ceil division
    chunks = []
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + chunk_size - 1)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + 1
    return chunks


class Application:
    def __init__(self, window: tk.Tk, dpi_scale: float = 1.0):
        self.window=window
        self.dpi_scale=dpi_scale
        window.title("Scan2Read — PDF를 듣는 책으로")
        window.geometry(f"{self._px(1000)}x{self._px(700)}")
        window.minsize(self._px(920),self._px(620))
        if sv_ttk is not None:
            # Windows' built-in ttk themes (the default "vista") look dated
            # next to Windows 11 -- sv_ttk applies a flat, modern "Sun Valley"
            # style to every ttk widget in one call. Must run on a real
            # tkinter.Tk before building widgets styled by it.
            try:
                sv_ttk.set_theme("light", root=window)
                _use_malgun_gothic(window)
            except tk.TclError:
                pass
        if dpi_scale != 1.0:
            # Fonts and ttk theme metrics are specified in points, which Tk
            # converts to pixels using this factor -- 96 DPI (Tk's assumed
            # baseline for "1.0") times our detected scale, over the 72
            # points-per-inch a point is defined as. Raw-pixel values (the
            # window/Treeview/wraplength geometry above and below) don't go
            # through this conversion at all, hence `_px()` for those instead.
            try:
                window.tk.call("tk","scaling",dpi_scale*96/72)
            except tk.TclError:
                pass
        self.events=queue.Queue()
        self.preferences=Preferences.load(self._settings_path())
        self._save_timer=None
        self._poll_timer=None
        self._closing=False
        for key, value in vars(self.preferences).items():
            variable=tk.BooleanVar(value=value) if isinstance(value,bool) else tk.StringVar(value=value)
            setattr(self,key,variable)
        self.source=tk.StringVar()
        self.output=tk.StringVar()
        stored_key=load_api_key(self._credentials_path(),self.ai_provider.get()) if self.remember_api_key.get() else ""
        self.api_key=tk.StringVar(value=os.environ.get(_PROVIDER_ENV_VAR[self.ai_provider.get()], "") or stored_key)
        self.api_status=tk.StringVar(value="저장된 키 있음 · 연결 확인 필요" if stored_key else "연결 확인 전")
        self.text_layer_status=tk.StringVar(value="")
        self.ai_estimate_status=tk.StringVar(value="AI 예상 사용량: 기능을 켜면 계산합니다.")
        self.ai_usage_status=tk.StringVar(value="실제 사용: 아직 없음")
        self.ai_progress_status=tk.StringVar(value="")
        self.gpu_name=None
        self.gpu_installed=False
        self.gpu_process=None
        self.gpu_install_button=None
        self.gpu_usage_status=tk.StringVar(value="")
        self.queue=[]
        self.in_batch=False
        # Batch scheduling state. A "job" is either {"kind":"ocr","file","range",
        # "chunk_index"} (OCR-only, no EPUB) or {"kind":"finalize","file","output",
        # optionally "chunk_index" when it is the file's only job -- see
        # _plan_file_jobs(). self.active maps a (file, kind[, chunk_index]) key to
        # {"process": Popen, "job": job}; self.job_queue holds not-yet-started jobs.
        self.job_queue=[]
        self.active={}
        self.chunk_plans={}       # file -> [(start,end), ...] for progress display
        self.chunk_progress={}    # file -> {chunk_index: last_absolute_page_seen}
        self.pending_chunk_count={}  # file -> OCR chunks not yet finished
        self.file_outputs={}      # file -> planned output Path
        self.failed_files=set()
        self.cancelled=False
        self.cancelling_remaining={}  # file -> its own active jobs not yet finished, while cancelling
        self.batch_total=0
        self.batch_failed=0
        self.last_successful_output=None
        self.row_states={}
        self.preview_outputs=[]
        self.page_counts={}
        self.inspecting_sources=set()
        self.current_ai_usage={}
        self.edit_controls=[]
        self.status=tk.StringVar(value="PDF를 추가하거나 창으로 끌어다 놓으세요.")
        frame=ttk.Frame(window,padding=20);frame.pack(fill="both",expand=True)
        ttk.Label(frame,text="Scan2Read",font=("맑은 고딕",22,"bold")).pack(anchor="w")
        notebook=ttk.Notebook(frame);notebook.pack(fill="both",expand=True,pady=(8,0))
        tab_convert=ttk.Frame(notebook,padding=10)
        tab_settings=ttk.Frame(notebook,padding=10)
        tab_ai=ttk.Frame(notebook,padding=10)
        notebook.add(tab_convert,text="변환")
        notebook.add(tab_settings,text="변환 설정")
        notebook.add(tab_ai,text="AI 설정")

        toolbar=ttk.Frame(tab_convert);toolbar.pack(fill="x",pady=8)
        for title,command in [("PDF 추가",self.choose_source),("폴더 추가",self.choose_source_folder),("선택 제거",self.remove_selected),("목록 비우기",self.clear_sources)]:
            button=ttk.Button(toolbar,text=title,command=command);button.pack(side="left",padx=(0,8))
            self.edit_controls.append((button,"normal"))
        self.count_label=ttk.Label(toolbar,text="0개 파일");self.count_label.pack(side="right")
        table_frame=ttk.Frame(tab_convert);table_frame.pack(fill="both",expand=True)
        ttk.Style(window).configure("Treeview",rowheight=self._px(30))
        self.file_list=ttk.Treeview(table_frame,columns=("source","output","state"),show="headings",height=8,selectmode="extended")
        for key,label,width in [("source","추가한 PDF",320),("output","저장될 EPUB",340),("state","상태",160)]:
            self.file_list.heading(key,text=label);self.file_list.column(key,width=self._px(width),minwidth=self._px(70))
        scroll=ttk.Scrollbar(table_frame,orient="vertical",command=self.file_list.yview)
        self.file_list.configure(yscrollcommand=scroll.set)
        self.file_list.pack(side="left",fill="both",expand=True);scroll.pack(side="right",fill="y")
        self.file_list.bind("<<TreeviewSelect>>",self._selection_changed)
        ttk.Label(tab_convert,textvariable=self.text_layer_status,foreground="#555").pack(anchor="w",pady=4)

        row=ttk.Frame(tab_settings);row.pack(fill="x",pady=6)
        ttk.Label(row,text="출력 폴더").pack(side="left")
        entry=ttk.Entry(row,textvariable=self.output_dir);entry.pack(side="left",fill="x",expand=True,padx=8)
        self.edit_controls.append((entry,"normal"))
        for title,command in [("폴더 선택",self.choose_output),("원본 폴더 사용",lambda:self.output_dir.set(""))]:
            button=ttk.Button(row,text=title,command=command);button.pack(side="left",padx=3)
            self.edit_controls.append((button,"normal"))
        ttk.Label(tab_settings,text="출력 폴더를 비우면 각 PDF와 같은 폴더에 저장합니다. 같은 이름은 (2), (3)을 붙입니다.").pack(anchor="w")
        row=ttk.Frame(tab_settings);row.pack(fill="x",pady=6)
        ttk.Label(row,text="파일명 규칙").pack(side="left")
        entry=ttk.Combobox(row,textvariable=self.name_rule,values=["{name}","{name}_낭독용","{index:03d}_{name}","{folder}_{name}"])
        entry.pack(side="left",fill="x",expand=True,padx=8);self.edit_controls.append((entry,"normal"))
        ttk.Label(tab_settings,text="{name}: 원본 이름 · {folder}: 원본 폴더명 · {index:03d}: 001부터 번호 · 확장자는 자동 추가").pack(anchor="w")
        options=ttk.Frame(tab_settings);options.pack(fill="x",pady=8)
        combo=ttk.Combobox(options,textvariable=self.columns,values=["1단","2단"],width=6,state="readonly")
        combo.pack(side="left",padx=(0,8));self.edit_controls.append((combo,"readonly"))
        for title,var in [("띄어쓰기 보정",self.spacing),("문맥·줄바꿈·문단 보정",self.reconstruct),("각주 제거",self.remove_footnotes),("괄호 안 내용 제거",self.remove_parentheses)]:
            check=ttk.Checkbutton(options,text=title,variable=var);check.pack(side="left",padx=6)
            self.edit_controls.append((check,"normal"))
        row=ttk.Frame(tab_settings);row.pack(fill="x",pady=4)
        check=ttk.Checkbutton(row,text="텍스트 레이어 무시하고 항상 OCR",variable=self.ignore_text_layer);check.pack(side="left")
        self.edit_controls.append((check,"normal"))
        ttk.Label(row,text="페이지 범위 (비우면 전체)").pack(side="left",padx=8)
        entry=ttk.Entry(row,textvariable=self.page_range,width=12);entry.pack(side="left")
        self.edit_controls.append((entry,"normal"))
        parallel_row=ttk.Frame(tab_settings);parallel_row.pack(fill="x",pady=4)
        ttk.Label(parallel_row,text="동시 처리 개수").pack(side="left")
        parallel_combo=ttk.Combobox(parallel_row,textvariable=self.max_parallel_conversions,
            values=["1","2","3","4"],width=4,state="readonly")
        parallel_combo.pack(side="left",padx=8);self.edit_controls.append((parallel_combo,"readonly"))
        ttk.Label(parallel_row,text="값이 클수록 GPU 메모리를 그만큼 더 씁니다(프로세스마다 독립적으로 모델을 올림) — "
                                     "부족하면 값을 줄이세요. 2 이상이면 큰 책은 페이지 구간을 나눠 병렬 OCR합니다.",
                  foreground="#555",wraplength=self._px(560)).pack(side="left")

        ai_row=ttk.Frame(tab_ai);ai_row.pack(fill="x",pady=4)
        check=ttk.Checkbutton(ai_row,text="AI 기능 전체 사용",variable=self.use_ai_context)
        check.pack(side="left");self.edit_controls.append((check,"normal"))
        ttk.Label(ai_row,text="제공자").pack(side="left",padx=(12,4))
        self.ai_provider_display=tk.StringVar(value=_PROVIDER_LABELS.get(self.ai_provider.get(),self.ai_provider.get()))
        provider_combo=ttk.Combobox(ai_row,textvariable=self.ai_provider_display,
            values=list(_PROVIDER_LABELS.values()),width=16,state="readonly")
        provider_combo.pack(side="left");self.edit_controls.append((provider_combo,"readonly"))
        self.ai_provider_display.trace_add("write",self._provider_display_changed)
        ttk.Label(ai_row,text="모델").pack(side="left",padx=(8,4))
        self.model_combo=ttk.Combobox(ai_row,textvariable=self.ai_model,width=22)
        self.model_combo.pack(side="left");self.edit_controls.append((self.model_combo,"normal"))
        self._refresh_model_choices()
        ai_key_row=ttk.Frame(tab_ai);ai_key_row.pack(fill="x",pady=2)
        ttk.Label(ai_key_row,text="API 키").pack(side="left")
        entry=ttk.Entry(ai_key_row,textvariable=self.api_key,show="•",width=34)
        entry.pack(side="left",fill="x",expand=True,padx=(4,0));self.edit_controls.append((entry,"normal"))
        button=ttk.Button(ai_key_row,text="연결 확인",command=self.check_api_connection)
        button.pack(side="left",padx=(6,0));self.edit_controls.append((button,"normal"))
        remember=ttk.Checkbutton(tab_ai,text="API 키 암호화 저장",variable=self.remember_api_key)
        remember.pack(anchor="w")
        self.edit_controls.append((remember,"normal"))
        ttk.Label(tab_ai,textvariable=self.api_status,foreground="#555").pack(anchor="w")
        self.model_verified_status=tk.StringVar(value="")
        self.model_status_label=ttk.Label(tab_ai,textvariable=self.model_verified_status,foreground="#555")
        self.model_status_label.pack(anchor="w")
        features=ttk.LabelFrame(tab_ai,text="선택한 AI 제공자 전용 기능 — 선택한 텍스트 일부가 API로 전송됩니다",padding=6)
        features.pack(fill="x",pady=(4,6))
        feature_values=[("문단 경계 검사",self.ai_boundary),("OCR 의심 단어 보정",self.ai_ocr_words),
                        ("띄어쓰기 AI 재검사",self.ai_spacing),("이상한 글자 탐지",self.ai_anomalies),
                        ("제목·본문·각주 분류",self.ai_structure),("장·절 구조 및 목차 감지",self.ai_headings),
                        ("괄호·음역 중복 표현 삭제",self.ai_glosses)]
        for index,(title,var) in enumerate(feature_values):
            feature=ttk.Checkbutton(features,text=title,variable=var)
            feature.grid(row=index//3,column=index%3,sticky="w",padx=(0,18),pady=2)
            self.edit_controls.append((feature,"normal"))
        cost_row=ttk.Frame(tab_ai);cost_row.pack(fill="x",pady=(0,3))
        ttk.Label(cost_row,text="책 한 권당 비용 한도 (USD)").pack(side="left")
        limit_entry=ttk.Entry(cost_row,textvariable=self.ai_cost_limit_usd,width=10)
        limit_entry.pack(side="left",padx=8);self.edit_controls.append((limit_entry,"normal"))
        ttk.Label(cost_row,text="비우면 한도 없음 · 한도 직전에 로컬 처리로 자동 전환",foreground="#555").pack(side="left")
        ttk.Label(tab_ai,textvariable=self.ai_estimate_status,foreground="#315a8a",wraplength=self._px(760)).pack(anchor="w")
        ttk.Label(tab_ai,textvariable=self.ai_usage_status,foreground="#315a8a",wraplength=self._px(760)).pack(anchor="w")
        ttk.Label(tab_ai,textvariable=self.ai_progress_status,foreground="#315a8a",wraplength=self._px(760)).pack(anchor="w",pady=(1,4))

        self.gpu_frame=ttk.Frame(tab_settings);self.gpu_frame.pack(fill="x",pady=(8,8))
        threading.Thread(target=self._check_gpu_status,daemon=True).start()
        if DND_FILES is not None:
            try:
                window.drop_target_register(DND_FILES)
                window.dnd_bind("<<Drop>>", self._on_drop)
            except (AttributeError, tk.TclError):
                pass
        actions=ttk.Frame(tab_convert);actions.pack(fill="x",pady=12)
        self.start_button=ttk.Button(actions,text="변환 시작 / 재개",command=self.start);self.start_button.pack(side="left")
        self.stop_button=ttk.Button(actions,text="중단",command=self.stop,state="disabled");self.stop_button.pack(side="left",padx=8)
        self.open_button=ttk.Button(actions,text="결과 파일 위치 열기",command=self.open_output,state="disabled");self.open_button.pack(side="right")
        self.progress=ttk.Progressbar(tab_convert,mode="determinate");self.progress.pack(fill="x",pady=8)
        ttk.Label(tab_convert,textvariable=self.status,wraplength=self._px(650)).pack(anchor="w")
        self.log=tk.Text(tab_convert,height=6,state="disabled",font=("맑은 고딕",9));self.log.pack(fill="both",expand=True,pady=(8,0))
        ttk.Label(tab_convert,text="중단 후 같은 PDF로 재개하면 완료된 OCR을 재사용합니다.").pack(anchor="w",pady=(8,0))
        window.protocol("WM_DELETE_WINDOW",self.close)
        self._poll_timer=window.after(150,self.poll)
        for key in vars(self.preferences):
            getattr(self,key).trace_add("write",self._settings_changed)
        self.api_key.trace_add("write",self._api_key_changed)
        self.ai_model.trace_add("write",self._model_verified_changed)
        self._model_verified_changed()


    def _px(self,value):
        """Scale a literal pixel constant (window/Treeview/wraplength geometry)
        by the detected DPI factor. Unlike fonts and ttk theme metrics -- which
        are in points and get Tk's own `tk scaling` conversion for free --
        these are raw pixel counts Tk passes straight through unscaled."""
        return round(value*self.dpi_scale)

    def _settings_path(self):
        return Path(os.environ.get("LOCALAPPDATA",str(Path.home())))/"Scan2Read"/"settings.json"

    def _credentials_path(self):
        return self._settings_path().with_name("credentials.json")

    def _api_key_changed(self,*_):
        if not self._closing:
            self.api_status.set("연결 확인 필요" if self.api_key.get().strip() else "API 키 없음 · 로컬 보정 사용")

    def _save_credentials(self):
        save_api_key(self._credentials_path(),self.ai_provider.get(),
                     self.api_key.get() if self.remember_api_key.get() else "")

    def _provider_display_changed(self,*_):
        provider=_PROVIDER_NAMES.get(self.ai_provider_display.get())
        if provider is None or provider==self.ai_provider.get():return
        self.ai_provider.set(provider)
        stored_key=load_api_key(self._credentials_path(),provider) if self.remember_api_key.get() else ""
        self.api_key.set(os.environ.get(_PROVIDER_ENV_VAR[provider],"") or stored_key)
        self._refresh_model_choices()

    def _refresh_model_choices(self):
        provider=self.ai_provider.get()
        specs=models_for(provider)
        self.model_combo["values"]=[spec.model for spec in specs]
        if specs and self.ai_model.get() not in [spec.model for spec in specs]:
            self.ai_model.set(default_model(provider) or specs[0].model)

    def _model_verified_changed(self,*_):
        spec=resolve_model(self.ai_provider.get(),self.ai_model.get())
        rate=f"백만 토큰당 입력 ${spec.input_price:g} · 출력 ${spec.output_price:g}"
        self.model_verified_status.set(
            rate if spec.verified else
            f"⚠ 목록에 없는 모델 — 요금을 몰라 이 제공자의 가장 비싼 모델 기준({rate})으로 비용을 추정합니다.")
        self.model_status_label.configure(foreground="#555" if spec.verified else "#b5651d")

    def check_api_connection(self):
        key=self.api_key.get().strip()
        provider=self.ai_provider.get();model=self.ai_model.get()
        if not key:
            self.api_status.set("API 키 없음 · 로컬 보정 사용");return
        label=_PROVIDER_LABELS.get(provider,provider)
        self.api_status.set(f"{label} {model} 연결 확인 중…")
        def check():
            try:
                from scan2read.cleanup.ai_providers import check_access
                check_access(provider,model,key)
                self.events.put(("api-check",(True,key,f"{label} {model} 연결됨")))
            except Exception as exc:
                self.events.put(("api-check",(False,key,str(exc))))
        threading.Thread(target=check,daemon=True).start()

    def _settings_changed(self,*_):
        if self._closing:return
        if not self.in_batch:self._refresh_list()
        if self._save_timer:self.window.after_cancel(self._save_timer)
        self._save_timer=self.window.after(400,self._save_settings)

    def _save_settings(self):
        self._save_timer=None
        try:
            Preferences(**{key:getattr(self,key).get() for key in vars(self.preferences)}).save(self._settings_path())
        except OSError as exc:
            self.status.set(f"설정 저장 실패: {exc}")

    def choose_source(self):
        if self.active or self.in_batch:return
        paths=filedialog.askopenfilenames(filetypes=[("PDF","*.pdf")])
        if paths:self._set_sources(list(paths))

    def choose_source_folder(self):
        if self.active or self.in_batch:return
        path=filedialog.askdirectory(title="PDF가 있는 폴더 선택")
        if not path:return
        pdfs=pdfs_from_inputs([path])
        if not pdfs:
            messagebox.showinfo("PDF 없음","선택한 폴더 바로 아래에 PDF 파일이 없습니다.");return
        self._set_sources(pdfs)
        self.status.set(f"폴더에서 PDF {len(pdfs)}개를 추가했습니다.")

    def _on_drop(self,event):
        if self.active or self.in_batch:return
        paths=pdfs_from_inputs(parse_dropped_paths(event.data))
        if not paths:
            messagebox.showerror("파일 확인","PDF 파일 또는 PDF가 있는 폴더를 끌어다 놓으세요.");return
        before=len(self.queue)
        self._set_sources(paths)
        added=len(self.queue)-before
        self.status.set(f"PDF {added}개를 추가했습니다." if added else "이미 목록에 있는 PDF입니다.")

    def _set_sources(self,paths):
        if self.in_batch:return
        existing={str(Path(p).resolve()).casefold() for p in self.queue}
        added=[]
        for path in paths:
            normalized=str(Path(path).resolve())
            if normalized.casefold() not in existing:
                self.queue.append(normalized);existing.add(normalized.casefold())
                self.row_states[normalized]="대기"
                added.append(normalized)
        self._refresh_list()
        for path in added:self._start_source_inspection(path)

    def _set_source(self,path):
        self._set_sources([path])

    def remove_selected(self):
        if self.in_batch:return
        selected={int(i) for i in self.file_list.selection()}
        self.queue=[p for i,p in enumerate(self.queue) if i not in selected]
        self._refresh_list()

    def clear_sources(self):
        if self.in_batch:return
        self.queue=[];self.row_states={};self.page_counts={};self._refresh_list()

    def _refresh_list(self):
        selected=self.file_list.selection()
        self.file_list.delete(*self.file_list.get_children())
        try:
            self.preview_outputs=plan_outputs([Path(p) for p in self.queue],self.output_dir.get(),self.name_rule.get())
            error=None
        except ValueError as exc:
            self.preview_outputs=[];error=str(exc)
        for i,path in enumerate(self.queue):
            output=self.preview_outputs[i].name if not error else error
            self.file_list.insert("","end",iid=str(i),values=(Path(path).name,output,self.row_states.get(path,"대기")))
        for item in selected:
            if self.file_list.exists(item):self.file_list.selection_add(item)
        self.count_label.configure(text=f"{len(self.queue)}개 파일")
        self._refresh_ai_estimate()

    def _enabled_ai_features(self):
        if not self.use_ai_context.get():return []
        values=(("boundary",self.ai_boundary),("ocr_words",self.ai_ocr_words),
                ("spacing",self.ai_spacing),("anomalies",self.ai_anomalies),
                ("structure",self.ai_structure),("headings",self.ai_headings),
                ("glosses",self.ai_glosses))
        return [name for name,variable in values if variable.get()]

    def _page_count_for_estimate(self,total):
        pages=self.page_range.get().strip()
        if not pages:return total
        match=re.fullmatch(r"(\d+)-(\d+)",pages)
        if not match:return total
        start,end=map(int,match.groups())
        return max(0,min(total,end)-start+1)

    def _refresh_ai_estimate(self):
        features=self._enabled_ai_features()
        if not features:
            self.ai_estimate_status.set("AI 예상 사용량: GPT 기능 꺼짐 · $0")
            return
        known=[self._page_count_for_estimate(self.page_counts[path])
               for path in self.queue if path in self.page_counts]
        if len(known)!=len(self.queue):
            self.ai_estimate_status.set("AI 예상 사용량: PDF 페이지 수 확인 중…")
            return
        model=resolve_model(self.ai_provider.get(),self.ai_model.get())
        estimates=[estimate_book_usage(pages,features,model=model) for pages in known]
        input_tokens=sum(item.input_tokens for item in estimates)
        output_tokens=sum(item.output_tokens for item in estimates)
        maximum=max((item.maximum_cost_usd for item in estimates),default=0)
        limit=self.ai_cost_limit_usd.get().strip()
        limit_text=f" · 설정 한도 ${float(limit):.2f}" if limit and self._valid_cost_limit(limit) else ""
        self.ai_estimate_status.set(
            f"변환 전 예상: 입력 {input_tokens:,} · 출력 {output_tokens:,} 토큰 · "
            f"책당 예상 최대 ${maximum:.4f}{limit_text}")

    @staticmethod
    def _valid_cost_limit(value):
        if not value:return True
        try:return float(value)>=0
        except ValueError:return False

    @staticmethod
    def _valid_parallel_count(value):
        try:return 1<=int(value)<=4
        except ValueError:return False

    def _max_parallel(self):
        try:
            return max(1,min(4,int(self.max_parallel_conversions.get())))
        except ValueError:
            return 1

    def _start_source_inspection(self,path):
        if path in self.page_counts or path in self.inspecting_sources:return
        self.inspecting_sources.add(path)
        threading.Thread(target=self._inspect_source,args=(path,),daemon=True).start()

    def _selection_changed(self,*_):
        selected=self.file_list.selection()
        if not selected:return
        path=self.queue[int(selected[0])]
        if self.source.get()==path:return
        self.source.set(path)
        self.text_layer_status.set("텍스트 레이어 확인 중…")
        self._start_source_inspection(path)

    def _inspect_source(self,path):
        root,python=self._runtime_python()
        env=os.environ.copy();env["PYTHONUTF8"]="1"
        env["PYTHONPATH"]=str(root/"app") if (root/"app").exists() else str(root/"src")
        try:
            result=subprocess.run([str(python),"-m","scan2read","inspect",path],capture_output=True,
                text=True,encoding="utf-8",errors="replace",env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0,timeout=120)
            summary=json.loads(result.stdout) if result.returncode==0 else None
        except (OSError,subprocess.TimeoutExpired,ValueError):summary=None
        self.events.put(("text-layer",(path,summary)))

    def _runtime_python(self):
        root=app_root()
        python=root/"runtime"/"python.exe"
        if not python.exists():python=root/".tools"/"paddle-env"/"Scripts"/"python.exe"
        return root,python

    def _check_gpu_status(self):
        root,python=self._runtime_python()
        env=os.environ.copy();env["PYTHONUTF8"]="1"
        env["PYTHONPATH"]=str(root/"app") if (root/"app").exists() else str(root/"src")
        try:
            result=subprocess.run([str(python),"-m","scan2read","gpu-status"],
                capture_output=True,text=True,encoding="utf-8",errors="replace",env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0,timeout=15)
            status=json.loads(result.stdout) if result.returncode==0 else None
        except (OSError,subprocess.TimeoutExpired,ValueError):
            status=None
        self.events.put(("gpu-status",status))

    def _poll_gpu_usage(self):
        root,python=self._runtime_python()
        env=os.environ.copy();env["PYTHONUTF8"]="1"
        env["PYTHONPATH"]=str(root/"app") if (root/"app").exists() else str(root/"src")
        while not self._closing:
            try:
                result=subprocess.run([str(python),"-m","scan2read","gpu-usage"],
                    capture_output=True,text=True,encoding="utf-8",errors="replace",env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0,timeout=10)
                data=json.loads(result.stdout) if result.returncode==0 else None
            except (OSError,subprocess.TimeoutExpired,ValueError):
                data=None
            self.events.put(("gpu-usage",data))
            time.sleep(3)

    def _show_gpu_usage(self,data):
        if not data:
            self.gpu_usage_status.set("");return
        used=data.get("memory_used_mb",0)/1024
        total=data.get("memory_total_mb",0)/1024
        self.gpu_usage_status.set(f"GPU 사용률 {data.get('utilization_percent',0)}% · VRAM {used:.1f}/{total:.1f}GB")

    def _start_gpu_install(self):
        if self.active or self.gpu_process or self.in_batch:return
        if not messagebox.askyesno("GPU 가속 설치",
                "NVIDIA CUDA 라이브러리 약 2GB를 내려받아 설치합니다. 계속할까요?"):
            return
        root,python=self._runtime_python()
        env=os.environ.copy();env["PYTHONUTF8"]="1";env["PYTHONUNBUFFERED"]="1"
        env["PYTHONPATH"]=str(root/"app") if (root/"app").exists() else str(root/"src")
        try:
            self.gpu_process=subprocess.Popen([str(python),"-m","scan2read","gpu-install"],
                stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding="utf-8",errors="replace",
                env=env,creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
        except OSError as exc:
            messagebox.showerror("실행 오류",str(exc));return
        self.gpu_install_button.configure(state="disabled",text="GPU 가속 설치 중…")
        self.start_button.configure(state="disabled")
        self.status.set("GPU 가속 설치 중입니다. 완료까지 시간이 걸릴 수 있습니다.")
        process=self.gpu_process
        def read():
            for line in process.stdout:self.events.put(("gpu-log",line))
            self.events.put(("gpu-done",process.wait()))
        threading.Thread(target=read,daemon=True).start()

    def choose_output(self):
        if self.in_batch:return
        path=filedialog.askdirectory(title="EPUB을 저장할 폴더 선택",initialdir=self.output_dir.get() or None)
        if path:self.output_dir.set(path)

    def _lock_controls(self,locked):
        for control,state in self.edit_controls:
            control.configure(state="disabled" if locked else state)
        self.start_button.configure(state="disabled" if locked else "normal")
        self.stop_button.configure(state="normal" if locked else "disabled")

    def _file_page_bounds(self,source):
        """(start, end) absolute page range this file will convert, or None if
        the page count isn't known yet (inspection still running)."""
        total=self.page_counts.get(source)
        if not total:return None
        pages=self.page_range.get().strip()
        match=re.fullmatch(r"(\d+)-(\d+)",pages) if pages else None
        if match:
            start,end=int(match[1]),int(match[2])
            return (max(1,start),min(total,end))
        return (1,total)

    def start(self):
        if self.active or self.gpu_process or self.in_batch:return
        if not self.queue:
            messagebox.showerror("파일 확인","변환할 PDF를 추가하세요.");return
        pages=self.page_range.get().strip()
        if pages:
            match=re.fullmatch(r"(\d+)-(\d+)",pages)
            if not match or not 1<=int(match[1])<=int(match[2]):
                messagebox.showerror("페이지 범위 확인","페이지 범위는 '30-50'처럼 입력하세요.");return
        try:
            outputs=plan_outputs([Path(p) for p in self.queue],self.output_dir.get(),self.name_rule.get())
            for p in self.queue:
                if not Path(p).is_file() or Path(p).suffix.lower()!=".pdf":raise ValueError(f"PDF 파일을 찾을 수 없습니다: {p}")
            if self.output_dir.get() and Path(self.output_dir.get()).is_file():raise ValueError("출력 위치는 폴더여야 합니다.")
            limit=self.ai_cost_limit_usd.get().strip()
            if not self._valid_cost_limit(limit):raise ValueError("책 한 권당 비용 한도는 0 이상의 USD 금액이어야 합니다.")
            if not self._valid_parallel_count(self.max_parallel_conversions.get()):
                raise ValueError("동시 처리 개수는 1~4 사이의 정수여야 합니다.")
        except ValueError as exc:
            messagebox.showerror("변환 설정 확인",str(exc));return
        self._save_settings()
        try:
            self._save_credentials()
        except OSError as exc:
            self.api_status.set(f"API 키 저장 실패: {exc}")
        self.job_queue=[]
        self.active={}
        self.chunk_plans={}
        self.chunk_progress={}
        self.pending_chunk_count={}
        self.file_outputs={}
        self.failed_files=set()
        self.cancelling_remaining={}
        self.batch_total=len(self.queue);self.batch_failed=0
        self.in_batch=True;self.cancelled=False
        self.current_ai_usage={}
        self.ai_progress_status.set("")
        if self._enabled_ai_features() and self.api_key.get().strip():
            self.ai_usage_status.set("실제 사용: GPT 호출 대기 중")
        elif self._enabled_ai_features():
            self.ai_usage_status.set("실제 사용: API 키 없음 · 로컬 처리 · $0")
        else:
            self.ai_usage_status.set("실제 사용: GPT 기능 꺼짐 · $0")
        self._lock_controls(True)
        max_parallel=self._max_parallel()
        for source,output in zip(self.queue,outputs):
            self.file_outputs[source]=output
            self.row_states[source]="대기"
            bounds=self._file_page_bounds(source)
            chunks=_plan_chunks(*bounds,max_parallel) if bounds else None
            if chunks and len(chunks)>1:
                self.chunk_plans[source]=chunks
                self.pending_chunk_count[source]=len(chunks)
                self.chunk_progress[source]={}
                for index,chunk_range in enumerate(chunks):
                    self.job_queue.append({"kind":"ocr","file":source,"range":chunk_range,"chunk_index":index})
            else:
                job={"kind":"finalize","file":source,"output":output}
                if bounds:
                    self.chunk_plans[source]=[bounds]
                    job["chunk_index"]=0
                self.job_queue.append(job)
        self._refresh_list()
        self._fill_batch_slots()

    @staticmethod
    def _job_key(job):
        if job["kind"]=="ocr":return (job["file"],"ocr",job["chunk_index"])
        return (job["file"],"finalize")

    def _subprocess_env(self):
        root,_=self._runtime_python()
        env=os.environ.copy();env["PYTHONUTF8"]="1";env["PYTHONUNBUFFERED"]="1"
        env["PYTHONDONTWRITEBYTECODE"]="1"
        env["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"]="True"
        env["PYTHONPATH"]=str(root/"app") if (root/"app").exists() else str(root/"src")
        if (root/"models").exists():env["SCAN2READ_MODELS"]=str(root/"models")
        if self.use_ai_context.get() and self.api_key.get().strip():
            env[_PROVIDER_ENV_VAR[self.ai_provider.get()]]=self.api_key.get().strip()
        if (root/"java"/"bin").exists():env["PATH"]=str(root/"java"/"bin")+os.pathsep+env.get("PATH","")
        return env

    def _ocr_chunk_command(self,source,start,end):
        root,python=self._runtime_python()
        work=Path(os.environ.get("LOCALAPPDATA",str(Path.home())))/"Scan2Read"/"work"
        command=[str(python),"-m","scan2read","ocr-pages",str(Path(source).resolve()),
                 "--work-dir",str(work),"--engine","paddle","--columns",self.columns.get()[0],
                 "--pages",f"{start}-{end}"]
        if self.ignore_text_layer.get():command+=["--text-layer","off"]
        if self.gpu_installed and self.use_gpu.get():command.append("--gpu")
        return command

    def _finalize_command(self,source,output):
        root,python=self._runtime_python()
        jar=root/"epubcheck"/"epubcheck.jar"
        if not jar.exists():jar=root/".tools"/"epubcheck-5.3.0"/"epubcheck.jar"
        work=Path(os.environ.get("LOCALAPPDATA",str(Path.home())))/"Scan2Read"/"work"
        command=[str(python),"-m","scan2read","convert",str(Path(source).resolve()),"--output",str(output.resolve()),
                 "--work-dir",str(work),"--engine","paddle","--columns",self.columns.get()[0],"--epubcheck",str(jar)]
        if self.spacing.get():command.append("--spacing")
        if self.reconstruct.get() or self.use_ai_context.get():command.append("--reconstruct")
        if self.use_ai_context.get():
            for enabled,flag in [(self.ai_boundary.get(),"--ai-context"),
                (self.ai_ocr_words.get(),"--ai-ocr-words"),(self.ai_spacing.get(),"--ai-spacing"),
                (self.ai_anomalies.get(),"--ai-anomalies"),(self.ai_structure.get(),"--ai-structure"),
                (self.ai_headings.get(),"--ai-headings"),(self.ai_glosses.get(),"--ai-glosses")]:
                if enabled:command.append(flag)
            command+=["--ai-provider",self.ai_provider.get(),"--ai-model",self.ai_model.get()]
        if self.remove_footnotes.get():command.append("--remove-footnotes")
        if self.remove_parentheses.get():command.append("--remove-parentheses")
        if self.gpu_installed and self.use_gpu.get():command.append("--gpu")
        if self.ignore_text_layer.get():command+=["--text-layer","off"]
        pages=self.page_range.get().strip()
        if pages:command+=["--pages",pages]
        limit=self.ai_cost_limit_usd.get().strip()
        if self.use_ai_context.get() and limit:command+=["--ai-cost-limit-usd",limit]
        return command

    def _launch_job(self,job) -> bool:
        source=job["file"]
        if job["kind"]=="ocr":
            command=self._ocr_chunk_command(source,*job["range"])
        else:
            command=self._finalize_command(source,job["output"])
        env=self._subprocess_env()
        try:
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                text=True,encoding="utf-8",errors="replace",env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
        except OSError as exc:
            messagebox.showerror("실행 오류",str(exc));return False
        key=self._job_key(job)
        self.active[key]={"process":process,"job":job}
        self.stop_button.configure(state="normal")
        self.open_button.configure(state="disabled")
        def read():
            for line in process.stdout:self.events.put(("log",(key,line)))
            self.events.put(("done",(key,process.wait())))
        threading.Thread(target=read,daemon=True).start()
        return True

    def _fill_batch_slots(self):
        while len(self.active)<self._max_parallel() and self.job_queue:
            job=self.job_queue.pop(0)
            if not self._launch_job(job):
                self._fail_file(job["file"])
        self._maybe_finish_batch()

    def _fail_file(self,source):
        if source in self.failed_files:return
        self.failed_files.add(source)
        self.batch_failed+=1
        self.row_states[source]="실패"
        self._update_state(source)
        self.pending_chunk_count.pop(source,None)
        self.job_queue=[job for job in self.job_queue if job["file"]!=source]

    def _maybe_finish_batch(self):
        if self.active or self.job_queue:return
        self.in_batch=False;self._lock_controls(False)
        self.progress["value"]=100
        self.status.set(f"배치 완료: {self.batch_total}개 중 {self.batch_total-self.batch_failed}개 성공, {self.batch_failed}개 실패")

    def _update_state(self,source):
        index=str(self.queue.index(source))
        self.file_list.set(index,"state",self.row_states[source])

    def _update_row_progress(self,source):
        chunks=self.chunk_plans.get(source)
        if not chunks:return
        total=sum(b-a+1 for a,b in chunks)
        progress=self.chunk_progress.get(source,{})
        done=sum(min(progress[i],b)-a+1 for i,(a,b) in enumerate(chunks) if i in progress)
        self.row_states[source]=f"OCR {done}/{total}쪽"
        self._update_state(source)
        completed_files=sum(1 for state in self.row_states.values() if state=="완료")
        if self.batch_total:
            self.progress["value"]=completed_files/self.batch_total*100

    def poll(self):
        while not self.events.empty():
            kind,value=self.events.get()
            if kind=="log":
                key,line=value
                self._handle_job_log(key,line)
            elif kind=="text-layer":
                path,value=value
                self.inspecting_sources.discard(path)
                if value:self.page_counts[path]=int(value.get("page_count",0))
                self._refresh_ai_estimate()
                if path!=self.source.get():continue
                if not value:
                    self.text_layer_status.set("")
                else:
                    pages=value.get("page_count",0);detected=value.get("pages_with_text_layer",0)
                    if pages==0:
                        self.text_layer_status.set("")
                    elif detected==0:
                        self.text_layer_status.set(f"이미지 스캔으로 판단됩니다 (총 {pages}페이지) — OCR로 처리합니다.")
                    elif detected==pages:
                        self.text_layer_status.set(f"텍스트 레이어 감지: 전체 {pages}페이지 — OCR 없이 텍스트를 바로 사용합니다.")
                    else:
                        self.text_layer_status.set(f"텍스트 레이어 감지: {pages}페이지 중 {detected}페이지 — 나머지는 OCR로 처리합니다.")
            elif kind=="gpu-status":
                if value and value.get("gpu_name"):
                    self.gpu_name=value["gpu_name"]
                    self.gpu_installed=bool(value.get("installed"))
                    ttk.Label(self.gpu_frame,text=f"NVIDIA {self.gpu_name} 감지됨",foreground="#555").pack(side="left")
                    if self.gpu_installed:
                        check=ttk.Checkbutton(self.gpu_frame,text="GPU 가속 사용",variable=self.use_gpu)
                        check.pack(side="left",padx=8)
                        self.edit_controls.append((check,"normal"))
                        if self.in_batch:check.configure(state="disabled")
                    else:
                        self.gpu_install_button=ttk.Button(self.gpu_frame,text="GPU 가속 다운로드 (~2GB)",
                            command=self._start_gpu_install)
                        self.gpu_install_button.pack(side="left",padx=8)
                    ttk.Label(self.gpu_frame,textvariable=self.gpu_usage_status,foreground="#555").pack(side="left",padx=8)
                    threading.Thread(target=self._poll_gpu_usage,daemon=True).start()
            elif kind=="gpu-usage":
                self._show_gpu_usage(value)
            elif kind=="api-check":
                success,key,message=value
                if key != self.api_key.get().strip():continue
                self.api_status.set(message)
                if success:
                    try:
                        self._save_credentials()
                    except OSError as exc:self.api_status.set(f"연결됨 · API 키 저장 실패: {exc}")
            elif kind=="gpu-log":
                self.log.configure(state="normal");self.log.insert("end",value);self.log.see("end");self.log.configure(state="disabled")
            elif kind=="gpu-done":
                self.gpu_process=None;self.start_button.configure(state="normal")
                if value==0:
                    self.gpu_installed=True;self.use_gpu.set(True)
                    self.gpu_install_button.destroy()
                    check=ttk.Checkbutton(self.gpu_frame,text="GPU 가속 사용",variable=self.use_gpu)
                    check.pack(side="left",padx=8);self.edit_controls.append((check,"normal"))
                    self.status.set("GPU 가속 설치를 완료했습니다.")
                else:
                    self.gpu_install_button.configure(state="normal",text="GPU 가속 다운로드 (~2GB)")
                    self.status.set("GPU 가속 설치에 실패했습니다. 아래 로그를 확인하세요.")
            elif kind=="done" and self.in_batch:
                key,code=value
                self._handle_job_done(key,code)
        if not self._closing:self._poll_timer=self.window.after(150,self.poll)

    def _handle_job_log(self,key,line):
        source,*_=key
        if line.startswith("SCAN2READ_AI_USAGE "):
            try:self._show_ai_usage(source,json.loads(line.partition(" ")[2]))
            except (ValueError,TypeError):pass
            return
        if line.startswith("SCAN2READ_AI_PROGRESS "):
            try:self._show_ai_progress(json.loads(line.partition(" ")[2]))
            except (ValueError,TypeError):pass
            return
        self.log.configure(state="normal");self.log.insert("end",f"[{Path(source).name}] {line}")
        self.log.see("end");self.log.configure(state="disabled")
        entry=self.active.get(key)
        if entry is not None and "chunk_index" in entry["job"]:
            match=_PAGE_PROGRESS.search(line)
            if match:
                n,_total=map(int,match.groups())
                self.chunk_progress.setdefault(source,{})[entry["job"]["chunk_index"]]=n
                self._update_row_progress(source)
        if len(self.queue)==1 and not self.batch_failed:
            total=self.batch_total or 1
            done=sum(1 for state in self.row_states.values() if state=="완료")
            self.status.set(f"[{done}/{total}] {Path(source).name} 변환 중…")

    def _handle_job_done(self,key,code):
        entry=self.active.pop(key,None)
        if entry is None:return
        job=entry["job"]
        source=job["file"]
        if self.cancelled:
            self._file_job_finished_while_cancelled(source)
            return
        if job["kind"]=="ocr":
            self._chunk_done(source,job,code)
        else:
            self._finalize_done(source,job,code)
        self._fill_batch_slots()

    def _chunk_done(self,source,job,code):
        if code!=0:
            self._fail_file(source)
            return
        if source in self.failed_files:return
        start,end=job["range"]
        self.chunk_progress.setdefault(source,{})[job["chunk_index"]]=end
        self._update_row_progress(source)
        self.pending_chunk_count[source]-=1
        if self.pending_chunk_count[source]<=0:
            self.row_states[source]="OCR 완료 · EPUB 조립 중…"
            self._update_state(source)
            self.job_queue.insert(0,{"kind":"finalize","file":source,"output":self.file_outputs[source]})

    def _finalize_done(self,source,job,code):
        if source in self.failed_files:return
        if code==0:
            self.last_successful_output=job["output"]
            self.open_button.configure(state="normal")
            self.row_states[source]="완료"
        else:
            self._fail_file(source)
        self._update_state(source)

    def _file_job_finished_while_cancelled(self,source):
        self.cancelling_remaining[source]-=1
        if self.cancelling_remaining[source]<=0 and self.row_states.get(source)!="중단":
            self.row_states[source]="중단"
            self._update_state(source)
        if self.active:return
        remaining_files={job["file"] for job in self.job_queue}
        for file in remaining_files:
            self.row_states[file]="취소"
            self._update_state(file)
        self.job_queue=[]
        self.in_batch=False;self._lock_controls(False)
        self.status.set("배치를 중단했습니다. 완료된 OCR은 재개할 때 재사용합니다.")

    def _show_ai_usage(self,source,snapshot):
        self.current_ai_usage[source]=snapshot
        total_in=sum(s.get("input_tokens",0) for s in self.current_ai_usage.values())
        total_out=sum(s.get("output_tokens",0) for s in self.current_ai_usage.values())
        total_cost=sum(s.get("cost_usd",0) for s in self.current_ai_usage.values())
        limit_reached=any(s.get("limit_reached") for s in self.current_ai_usage.values())
        features={}
        for snap in self.current_ai_usage.values():
            for name,item in snap.get("features",{}).items():
                agg=features.setdefault(name,{"requests":0,"input_tokens":0,"output_tokens":0,"cost_usd":0.0})
                agg["requests"]+=item.get("requests",0)
                agg["input_tokens"]+=item.get("input_tokens",0)
                agg["output_tokens"]+=item.get("output_tokens",0)
                agg["cost_usd"]+=item.get("cost_usd",0)
        feature_lines=[f"{FEATURE_LABELS.get(name,name)} {agg['requests']}회 {agg['input_tokens']:,}/{agg['output_tokens']:,} ${agg['cost_usd']:.4f}"
                       for name,agg in features.items()]
        state=" · 한도 도달, 남은 작업은 로컬 처리" if limit_reached else ""
        detail=" · 기능별 배분(요청·입력/출력): "+", ".join(feature_lines) if feature_lines else ""
        self.ai_usage_status.set(
            f"실제 누적(진행 중인 파일 합계): 입력 {total_in:,} · "
            f"출력 {total_out:,} 토큰 · ${total_cost:.4f}"
            f"{state}{detail}")

    def _show_ai_progress(self,snapshot):
        stage={"ai_context":"문단 경계 검사","ai_enhance":"AI 보정"}.get(snapshot.get("stage"),"AI 검수")
        completed=snapshot.get("completed_batches",0);total=snapshot.get("total_batches",0)
        if total==0:
            self.ai_progress_status.set("");return
        remaining=snapshot.get("estimated_remaining_seconds")
        eta=f" · 예상 남은 시간 {remaining:.0f}초" if remaining is not None else ""
        self.ai_progress_status.set(f"{stage} 진행률: {completed}/{total} 묶음{eta}")

    def stop(self):
        if not self.active:return
        self.cancelled=True
        self.cancelling_remaining={}
        for key,entry in self.active.items():
            self.cancelling_remaining[key[0]]=self.cancelling_remaining.get(key[0],0)+1
            entry["process"].terminate()
        self.status.set("중단 중입니다…")

    def open_output(self):
        if os.name!="nt":return
        output=self.last_successful_output
        if output is None:return
        if output.is_file():
            # A single quoted argument after the comma is required; passing
            # ["explorer", "/select,"+path] as separate argv items instead
            # makes Python's own argv-quoting wrap the WHOLE token (including
            # "/select,") whenever the path has a space, which Explorer fails
            # to parse and silently falls back to opening Documents instead.
            subprocess.run(f'explorer /select,"{output}"')
        elif output.parent.is_dir():os.startfile(output.parent)

    def close(self):
        if self.active:
            if not messagebox.askyesno("변환 중단","변환을 중단하고 종료할까요?"):return
            self.stop()
        if self.gpu_process:
            if not messagebox.askyesno("설치 중단","GPU 가속 설치를 중단하고 종료할까요?"):return
            self.gpu_process.terminate()
        self._save_settings()
        try:self._save_credentials()
        except OSError:pass
        self._closing=True
        for timer in (self._save_timer,self._poll_timer):
            if timer:self.window.after_cancel(timer)
        self.window.destroy()


def main():
    scale=dpi_scale()  # must run before the first Tk window is created
    if DND_FILES is not None:
        from tkinterdnd2 import TkinterDnD
        window=TkinterDnD.Tk()
    else:
        window=tk.Tk()
    Application(window,dpi_scale=scale);window.mainloop()


if __name__=="__main__":main()
