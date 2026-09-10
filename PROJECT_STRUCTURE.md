# Scan2Read 폴더 구조

실제 현재 구조입니다(권장안이 아니라 있는 그대로). `config/`, `document/`, `tts/`,
`image/`, `utils/`처럼 애초에 계획했지만 쓰지 않은 모듈은 만들지 않았고, TTS 전용
변환은 `cleanup/parentheses.py` 안에, 설정은 `project/batch.py`의 `Preferences` 안에
있는 식으로 실제로 필요할 때 기존 모듈에 붙였습니다.

```text
scan2read/
├─ README.md
├─ AGENTS.md
├─ CODEX_FIRST_PROMPT.md
├─ PROJECT_STRUCTURE.md
├─ pyproject.toml
├─ .gitignore
├─ Scan2Read.spec              # 포터블 GUI exe (PyInstaller)
├─ Scan2Read-Setup.spec        # 온라인 설치 exe (PyInstaller)
├─ Scan2Read-Setup-Debug.spec
│
├─ src/scan2read/
│  ├─ __init__.py
│  ├─ __main__.py
│  ├─ cli.py                   # convert / inspect / ocr-pages / gpu-status / gpu-install / gpu-usage
│  ├─ gui.py                   # Tkinter GUI (변환 / 변환 설정 / AI 설정 3탭)
│  ├─ pipeline.py               # convert() 오케스트레이션, 캐시 키, 세대 관리
│  │
│  ├─ pdf/
│  │  ├─ reader.py             # 페이지 수·메타데이터 검사
│  │  ├─ renderer.py           # 페이지 → PNG 렌더링
│  │  ├─ text_layer.py         # 기존 PDF 텍스트 레이어 재사용/부분 OCR 보정
│  │  └─ prefetch.py           # GPU 처리 중 다음 페이지 별도 프로세스 프리페치
│  │
│  ├─ ocr/
│  │  ├─ base.py               # OCR 엔진 추상 인터페이스
│  │  ├─ models.py             # OCRPage/OCRBlock 데이터 모델
│  │  ├─ paddle.py             # PaddleOCR 어댑터 (CPU/GPU)
│  │  ├─ tesseract.py          # Tesseract 어댑터
│  │  ├─ columns.py            # 2단 레이아웃 분리
│  │  └─ gpu.py                # NVIDIA GPU 감지·사용률·CUDA 빌드 설치
│  │
│  ├─ cleanup/
│  │  ├─ headers.py            # 반복 머리글·꼬리글 제거
│  │  ├─ footnotes.py          # 각주 제거 (opt-in)
│  │  ├─ noise.py              # 고립된 1~2글자 OCR 잡음 제거
│  │  ├─ parentheses.py        # 괄호 안 내용 제거 (TTS 전용 레이어)
│  │  ├─ reconstruction.py     # 좌표 기반 줄 결합·문단 복원
│  │  ├─ spacing.py            # Kiwi 기반 띄어쓰기 보정
│  │  ├─ context.py            # 문단 경계 판정(로컬 + AI 연동 지점)
│  │  ├─ text.py               # 공용 텍스트 유틸리티
│  │  ├─ ai_providers.py       # OpenAI/Anthropic/Google 클라이언트, 모델 요금표
│  │  ├─ ai_enhance.py         # AI 보정 옵션별 프롬프트·검증·적용 (AIOptions/AIEnhancer)
│  │  ├─ ai_filter.py          # AI로 보낼 문단 사전 필터링
│  │  ├─ ai_cache.py           # 문단·모델·기능 조합 캐시
│  │  └─ ai_usage.py           # 토큰·비용 추정과 집계
│  │
│  ├─ epub/
│  │  ├─ builder.py            # EPUB3 생성
│  │  └─ validator.py          # EPUBCheck 연동
│  │
│  └─ project/
│     ├─ storage.py            # work/ 캐시 레이아웃, project.json
│     ├─ batch.py              # GUI Preferences, 배치 작업 계획
│     └─ credentials.py        # 제공자별 API 키 암호화 저장 (Windows DPAPI)
│
├─ scripts/
│  ├─ gui_launcher.py          # Scan2Read.spec의 진입점
│  ├─ windows_installer.py     # Scan2Read-Setup.spec의 진입점 (설치 GUI)
│  ├─ stage_windows.py         # 포터블/온라인 페이로드 스테이징
│  └─ trial_*.py, benchmark_prefetch.py, cleanup_epub.py  # 실험·벤치마크 스크립트
│
├─ tests/                      # test_*.py, unittest 기반
│
└─ docs/
   ├─ INSTALL.md               # 설치 가이드 (사용자용)
   ├─ WINDOWS.md               # 사용 안내 (사용자용)
   ├─ CURRENT_SPEC.md          # 현재 구현 상태·인수인계 (개발자용)
   ├─ CHANGELOG.md             # 세션별 변경 이력과 그 이유 (개발자용)
   ├─ roadmap.md               # 남은 작업 (개발자용)
   ├─ architecture.md          # 기술 선택과 근거 (개발자용)
   └─ *-trial.md, gpu-prefetch-benchmark.md  # 특정 시점 실험 기록 (그 시점 스냅샷, 갱신 대상 아님)
```
