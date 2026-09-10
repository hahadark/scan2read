# Scan2Read

스캔한 PDF 책을 OCR로 읽고, 깨진 문장이나 중복된 표현을 정리해서, **운전하거나 걸을 때 TTS로 들을 수 있는 EPUB3**로 만들어주는 Windows 프로그램입니다.

- 한글 스캔 도서에 특화된 OCR (PaddleOCR / Tesseract)
- 오탈자·깨진 문장·중복 표현 자동 정리 (필요하면 AI로 한 번 더 다듬기 — 선택 사항)
- 결과물은 EPUB 리더 앱에서 TTS로 바로 들을 수 있는 EPUB3
- 처리는 전부 사용자 컴퓨터에서, 무료로 — PDF나 페이지 이미지를 외부로 보내지 않음

## 다운로드 및 설치

**[Releases 페이지](../../releases/latest)에서 `Scan2Read-Setup.exe`를 받아 실행하세요.** 관리자 권한은 필요 없습니다.

설치 파일 자체는 약 120MB이고, 설치 중 필요한 OCR 구성요소(PaddleOCR·Kiwi·한국어 모델, 약 250MB)를 인터넷에서 추가로 받습니다. 설치 후 디스크 사용량은 약 1.2GB입니다.

처음 실행하면 Windows가 "PC 보호" 경고를 띄울 수 있습니다(아직 정식 서명 인증서가 없는 초기 배포판이라 그렇습니다) — 자세한 절차와 문제 해결은 **[설치 가이드](docs/INSTALL.md)**를 확인하세요.

## 사용법

1. **변환** 탭에서 PDF를 추가하거나, PDF가 든 폴더를 창에 끌어다 놓습니다.
2. **변환 설정** 탭에서 출력 폴더, 파일명 규칙, 단(1/2단), 처리할 페이지 범위 등을 정합니다. 필요하면 GPU 가속과 동시 처리 개수도 여기서 켭니다.
3. (선택) **AI 설정** 탭에서 AI 보정을 쓰고 싶으면 제공자(OpenAI/Claude/Gemini)와 모델을 고르고 API 키를 입력합니다. 켜지 않아도 로컬 정리만으로 변환됩니다.
4. **변환** 탭으로 돌아와 변환 시작을 누릅니다. 끝나면 "결과 파일 위치 열기"로 EPUB을 찾아 전자책 앱(또는 TTS 지원 리더)으로 옮기면 됩니다.

더 자세한 화면별 설명은 **[사용 안내](docs/WINDOWS.md)**에 있습니다.

## 요구 사항

- Windows 10/11 (x64)
- 설치 시 인터넷 연결 필요 (변환 자체는 오프라인으로 동작)
- GPU 가속은 **NVIDIA GPU(CUDA)만 지원**합니다 — 인텔/AMD 내장그래픽은 가속되지 않고 자동으로 CPU 모드로 동작합니다.

## 개발자용

소스에서 직접 빌드하거나 코드를 살펴보고 싶다면:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
$env:EPUBCHECK_JAR = (Resolve-Path .tools/epubcheck-5.3.0/epubcheck.jar).Path
.\.venv\Scripts\scan2read convert book.pdf --tesseract 'C:\Program Files\Tesseract-OCR\tesseract.exe'
```

테스트:

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
```

- 현재 구현 상태와 인수인계: [docs/CURRENT_SPEC.md](docs/CURRENT_SPEC.md)
- 변경 이력: [docs/CHANGELOG.md](docs/CHANGELOG.md)
- 남은 작업: [docs/roadmap.md](docs/roadmap.md)
- 아키텍처: [docs/architecture.md](docs/architecture.md)
- 원래 기획 문서(MVP 범위, 초기 설계 원칙): [CODEX_FIRST_PROMPT.md](CODEX_FIRST_PROMPT.md)

핵심 설계 원칙은 OCR 원본(Raw OCR)을 절대 직접 수정하지 않는 것입니다.

```text
Raw OCR → Clean Text → TTS Text
```

- Raw OCR: OCR 엔진이 반환한 원본 결과 (변경하지 않음)
- Clean Text: 의미와 표현을 유지하며 구조 오류만 정리한 결과
- TTS Text: 낭독 편의를 위한 추가 변환 결과 (예: 괄호 안 성경 구절 인용 제거)

## 라이선스 및 제3자 고지

설치본에 포함된 제3자 구성요소의 라이선스는 설치 폴더의 `runtime/LICENSE.txt`,
`runtime/Lib/site-packages`의 각 패키지 `dist-info/licenses`, `java/legal`,
`epubcheck/licenses`에 있습니다. Python은 PSF License, PaddleOCR/PaddlePaddle은
Apache-2.0, Kiwi는 LGPL-3.0, EPUBCheck는 BSD-3-Clause, Temurin(Java)은
GPL-2.0 with Classpath exception을 따릅니다.
