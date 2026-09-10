# Codex 최초 개발 프롬프트

README.md와 AGENTS.md를 먼저 읽고 이 프로젝트의 목적과 개발 원칙을 파악해 주세요.

이 프로젝트는 스캔된 한국어 책 PDF를 OCR 처리하여 TTS에 적합한 EPUB3으로 변환하는 Scan2Read입니다.

이번 작업에서는 전체 제품을 한 번에 구현하지 말고 **Phase 1 CLI MVP의 기반만 구축**합니다.

## 이번 작업 목표

다음 명령의 최소 end-to-end 동작을 구현하는 것이 목표입니다.

```bash
scan2read convert input.pdf
```

최종적으로 작은 테스트 PDF를 입력했을 때 EPUB 파일 하나가 생성되어야 합니다.

단, 실제 OCR 품질 개선이나 고급 문서 분석은 이번 작업의 범위가 아닙니다.

## 구현할 항목

### 1. Python 프로젝트 초기화

Python 3.12+ 기준으로 프로젝트를 구성해 주세요.

`src` layout을 사용합니다.

기본 구조는 README.md의 권장 구조를 따르되 아직 필요하지 않은 빈 모듈을 과도하게 만들 필요는 없습니다.

`pyproject.toml`을 생성하세요.

### 2. CLI

다음 명령을 구현하세요.

```bash
scan2read convert FILE
```

추가 옵션:

```text
--output
--work-dir
--dpi
--force
```

예:

```bash
scan2read convert samples/sample.pdf --output output/sample.epub
```

### 3. PDF Reader

PDF 파일을 열어 다음을 확인할 수 있도록 구현하세요.

- 파일 존재 여부
- 페이지 수
- 기본 메타데이터
- 페이지 렌더링 가능 여부

잘못된 PDF는 명확한 오류 메시지를 출력해야 합니다.

### 4. PDF Renderer

페이지를 개별 이미지로 렌더링하세요.

기본값: 300 DPI

전체 페이지를 동시에 메모리에 올리지 말고 페이지 단위로 처리하세요.

### 5. OCR Interface

특정 OCR 라이브러리에 비즈니스 로직이 종속되지 않도록 OCR abstraction을 작성하세요.

내부적으로 최소한 다음 정보를 표현할 수 있어야 합니다.

```text
OCRPage
OCRBlock
bbox
text
confidence
```

초기 OCR engine 구현은 하나만 있어도 됩니다.

한국어 OCR을 지원할 수 있는 엔진을 선택하되, 설치와 크로스플랫폼 호환성을 고려하세요.

선택 이유를 README 또는 architecture 문서에 간단히 기록하세요.

### 6. Raw OCR persistence

각 페이지 OCR 결과를 JSON으로 저장하세요.

예:

```text
work/project/raw_ocr/page_0001.json
```

Raw OCR 파일은 이후 단계에서 수정하거나 덮어쓰지 않습니다.

### 7. Clean Text

이번 버전에서는 복잡한 구조 분석을 하지 않습니다.

최소한 다음 두 가지 기능만 작성하세요.

- 페이지 상단/하단의 단순 숫자형 페이지 번호 제거
- OCR의 개별 줄을 기본적인 문장 텍스트로 연결

과도한 문장 교정은 하지 않습니다.

### 8. EPUB3 Builder

Clean Text 결과를 이용하여 Reflowable EPUB3을 생성하세요.

초기 버전에서는 책 전체를 하나의 XHTML chapter로 만들어도 됩니다.

최소 메타데이터:

```text
title
language = ko
```

PDF metadata에서 title을 얻을 수 있으면 활용하고, 없으면 파일명을 사용하세요.

### 9. Cache

Raw OCR JSON이 이미 존재하면 동일 페이지 OCR을 다시 실행하지 마세요.

`--force`가 지정된 경우만 다시 실행합니다.

### 10. Project Manifest

작업 디렉터리에 최소 프로젝트 정보를 기록하세요.

예:

```json
{
  "source": "...",
  "page_count": 20,
  "dpi": 300,
  "version": 1
}
```

### 11. Logging

사용자가 현재 진행 상황을 알 수 있도록 페이지 진행률을 표시하세요.

예:

```text
Rendering/OCR: 12 / 148
```

DEBUG 로그와 일반 사용자 출력을 분리할 수 있는 구조를 사용하세요.

### 12. Tests

최소 다음 테스트를 작성하세요.

- PDF reader
- OCR data model serialization
- page number cleanup
- line joining
- cache detection
- EPUB creation

실제 저작권 도서 파일을 테스트 fixture로 넣지 마세요.

필요하면 테스트용 PDF를 프로그램에서 생성하세요.

## 중요한 제한

이번 단계에서는 다음을 구현하지 마세요.

- GUI
- AI API
- OpenAI API
- TTS 음성 생성
- M4B
- 성경구절 변환
- 복잡한 제목 추론
- 복잡한 각주 처리
- 고급 2단 분석
- 클라우드 서비스
- 데이터베이스

향후 추가할 수 있도록 구조만 확장 가능하게 유지하세요.

## 개발 방식

한 번에 모든 코드를 작성하지 마세요.

다음 순서대로 진행하세요.

1. 저장소 구조와 의존성 설계
2. 최소 CLI
3. PDF reader
4. renderer
5. OCR abstraction
6. OCR persistence
7. cleanup
8. EPUB builder
9. end-to-end convert
10. tests

각 단계가 끝날 때 현재 테스트를 실행하고 오류가 있으면 먼저 해결하세요.

## 완료 후 보고

작업을 완료한 후 다음 내용을 정리해서 알려주세요.

1. 생성하거나 수정한 주요 파일
2. 선택한 OCR 엔진과 선택 이유
3. 프로그램 실행 방법
4. 테스트 실행 방법
5. 현재 MVP에서 가능한 것
6. 아직 구현하지 않은 것
7. 다음 개발 단계에서 가장 먼저 해야 할 작업

그리고 실제 가능한 경우 작은 샘플 PDF로 다음을 실행하여 EPUB이 생성되는 것까지 검증하세요.

```bash
scan2read convert sample.pdf
```
