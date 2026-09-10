# 구현 현황과 기술 선택

이 문서는 기술 선택과 그 근거를 다룬다. 현재 기능 목록과 제한 사항은
[CURRENT_SPEC.md](CURRENT_SPEC.md), 왜 그렇게 됐는지의 서사는
[CHANGELOG.md](CHANGELOG.md)를 참고한다.

## 단계별 진행

- 완료: CLI 기반 파이프라인(PDF → OCR → 정리 → EPUB3), 캐시·재개.
- 완료: Tkinter GUI(파일 목록, 배치 처리, 드래그 앤 드롭, 3탭 구성).
- 완료: PaddleOCR GPU 가속, 페이지 구간 분할 병렬 OCR.
- 완료: 선택적 AI 보정 레이어(OpenAI/Claude/Gemini).
- 완료: Windows 배포(포터블 exe + 온라인 설치 exe).

## 의존성

- PDF 렌더링: `pypdfium2`(Apache-2.0/BSD-3-Clause). 권장 스택의 PyMuPDF 대신 선택 —
  대체 가능한 내부 모듈 뒤에 감춰져 있다.
- 이미지: `Pillow`(MIT-CMU).
- OCR 엔진 두 종류, `ocr/base.py`의 공통 인터페이스 뒤에:
  - `Tesseract`: 최초 MVP에서 선택. Apache-2.0, 크로스플랫폼, 로컬 subprocess 실행,
    별도 대형 프레임워크 불필요. 기본 언어 `kor+eng`, PSM 6.
  - `PaddleOCR`(`ocr/paddle.py`): 실제 스캔본 검증 중 한글 인식률과 GPU 가속이
    필요해 추가. 검출 `PP-OCRv5_mobile_det` + 인식 `korean_PP-OCRv5_mobile_rec`
    조합. GPU는 NVIDIA CUDA(`paddlepaddle-gpu`)만 지원하며 CPU 대비 실측
    약 26배 빠르다. CPU/GPU 부동소수점 차이로 결과가 미세하게 달라질 수 있어
    `device`를 캐시 키에 포함한다.
- 형태소 분석: `Kiwi`(LGPL-3.0, 동적 라이브러리로 분리) — 띄어쓰기·문맥 판정에 사용,
  네트워크 없이 로컬에서 실행.
- EPUB: Python 표준 라이브러리로 직접 생성(EbookLib 미사용, 최소 구현으로 충분).
- 검증: `EPUBCheck`(BSD-3-Clause, Java).
- GUI 테마: `sv-ttk`(Windows 11 스타일). PyInstaller가 `.tcl`/이미지 자산을 자동
  인식하지 못해 `Scan2Read.spec`에 `collect_data_files('sv_ttk')`로 명시해야 한다.

## OCR 데이터 흐름과 캐시

`work/<설정 SHA256>/project.json`에 원본 경로·페이지 수·DPI·엔진·상태를 기록한다.
렌더링 결과는 `pages/`, 각 OCR 실행은 `generations/<세대>/raw_ocr/`(원본)과
`generations/<세대>/clean/`(정리 결과)에 저장한다. AI 보정을 쓰면 같은 세대 아래
`clean/ai_usage.json`(비용·토큰), `clean/ai_context.json`(문단 경계 판정),
`clean/ai_enhancements.json`(그 외 보정 결과)이 추가된다.

캐시 키는 원본 PDF 해시, DPI, OCR 엔진과 언어 모델 해시, PSM, `text_layer` 모드,
GPU 사용 여부로 결정된다. **페이지 범위는 캐시 키에 포함하지 않는다** — 그래서
`scan2read ocr-pages`로 겹치지 않는 페이지 구간을 여러 프로세스가 동시에 채워도
안전하고, 이후 전체 범위로 `convert`를 실행하면 그 캐시를 그대로 재사용해 OCR
없이 EPUB만 조립한다. GUI의 청크 스케줄러(`gui.py`)가 "동시 처리 개수" 설정만큼
`ocr-pages` 프로세스를 병렬로 띄우고, 모든 구간이 끝나면 `convert`를 한 번 더
호출해 EPUB을 마무리하는 방식이 이 캐시 설계 위에서 동작한다.

강제 재실행(`--force`)은 새 세대 디렉터리를 써서 기존 원본을 보존한다.

## AI 보정 레이어

`cleanup/ai_*.py`가 로컬 판정을 보강하는 선택적 레이어를 이룬다.

- `ai_providers.py`: OpenAI/Anthropic/Google 클라이언트와 모델별 요금표(`MODELS`).
  제공자별 기본값은 플래그십이 아니라 저비용·균형 모델. 실측 결과 비용 대비
  효과가 낮은 모델(GPT-6 Astra, GPT-5.6 Sol)은 목록에서 제외했다.
- `ai_filter.py`: 문단을 AI로 보낼지 로컬에서 걸러 비용을 줄인다.
- `ai_enhance.py`: `AIOptions` 데이터클래스 필드 하나가 기능 하나(문단 경계, OCR
  의심 단어, 띄어쓰기, 이상 문자, 구조 분류, 목차, 괄호·음역 삭제)에 대응한다.
  각 필드는 JSON 스키마 속성 + 프롬프트 문구 + 검증된 적용 메서드로 연결된다.
  응답은 항상 원문을 다시 쓰지 않고 구조화된 판정만 반환하도록 강제하며, 적용
  전 안전장치(정확히 한 번만 등장, 문단 길이 대비 비율 제한 등)를 통과해야 한다.
- `ai_cache.py`: 문단·모델·기능 조합을 여러 책·재실행에 걸쳐 캐시.
- `ai_usage.py`: 변환 전 예상 비용과 변환 중 실제 비용·진행률 계산.

오류 처리는 두 단계로 나뉜다 — 응답이 파싱 불가능하거나 스키마를 벗어나면 그
묶음만 로컬 판정으로 넘어가고 다음 묶음은 다시 시도한다. 연결 자체가 끊기면
(`OSError`) 그 책의 나머지 전체가 로컬 처리로 전환된다. Raw OCR과 PDF/페이지
이미지는 어떤 경우에도 외부로 전송하지 않는다.

## GUI와 배치 처리

Tkinter 기반, `TkinterDnD`로 드래그 앤 드롭을 지원한다(`gui.py`). 화면은 "변환"
(파일 목록·시작/중단·로그) · "변환 설정"(출력·이름 규칙·보정 옵션·GPU·동시 처리
개수) · "AI 설정"(제공자·모델·키·기능·비용) 3탭으로 나뉜다.

배치 처리는 `self.job_queue`(파일별 OCR 청크 + finalize 잡)와 `self.active`(현재
실행 중인 서브프로세스)로 이뤄진 슬롯 기반 스케줄러다. 동시 처리 개수만큼 슬롯을
채우고, 한 파일의 모든 OCR 청크가 끝나면 그 파일의 finalize(`convert`) 잡을 큐
앞에 넣는다. 진행률은 청크별 최신 페이지 번호를 합산해 계산한다. 취소 시 활성
프로세스에 `terminate()`를 보내고, 마지막 활성 잡이 끝난 뒤에야 남은 대기열을
파일 단위로 취소 처리한다.

## HiDPI와 테마

`dpi_scale()`이 `SetProcessDpiAwareness`로 DPI 인식을 켜고 실제 배율을 읽는다.
글꼴 등 점 단위 값은 Tk의 `tk scaling`으로, 창 크기·Treeview 폭 같은 픽셀 리터럴은
`Application._px()`로 각각 배율을 곱한다. `sv_ttk.set_theme()` 적용 직후 8개
Sun Valley 명명 폰트를 맑은 고딕으로 재설정한다(원래 폰트가 이 PC의 한글 폴백에
실패해서 생긴 조치).

## 패키징과 배포

`Scan2Read.spec`(PyInstaller)이 `scripts/gui_launcher.py`를 진입점으로 GUI 전체를
freeze한다. **`gui.py`가 임포트하는 모든 코드는 exe의 PYZ 안에 그대로 박제되므로**,
그 코드가 바뀌면 `app/scan2read`로의 단순 복사가 아니라 반드시 전체 재빌드가
필요하다. CLI 서브프로세스(`ocr-pages`/`convert`)만 `app/scan2read`의 소스를
그대로 읽는다.

배포는 두 가지다.

- 포터블(`dist/Scan2Read`): 개발/검증용, PaddleOCR·Kiwi 등을 전부 포함.
- 온라인 설치(`Scan2Read-Setup.exe`, `Scan2Read-Setup.spec`): 작은 exe(약 120MB)만
  배포하고, 설치 중 `scripts/windows_installer.py`가 CPU용 PaddleOCR·Kiwi·한국어
  모델(약 250MB)을 내려받는다. 관리자 권한 없이 사용자 폴더에 설치되며, 시작
  메뉴 바로가기와 "프로그램 및 기능" 제거 항목을 등록한다. GPU 가속(CUDA, 약 2GB)은
  설치 후 GUI에서 별도로 선택할 때만 받는다.

Windows 개발/빌드 환경 세부 사항(2026-09-07 검증 내용)은 다음과 같다.

- pypdfium2 5.x, Pillow 12.x를 Windows Python 3.12에서 설치·렌더링 검증했다.
  macOS 실행은 검증하지 않았다.
- 원본 JSON은 완성된 임시 파일을 hard link로 게시해 기존 파일을 덮어쓰지 않는다
  (같은 파일시스템의 hard link 지원 필요).
- EPUB은 페이지별로 처리해 ZIP 멤버에 순차 기록하고, HTML/XML 특수문자를
  이스케이프한다. 최소 메타데이터(title, ko 언어, UUID, 수정 시각)만 채운다.
  표지·저자·ISBN은 아직 없다.
