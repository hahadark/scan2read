# Scan2Read

스캔된 책 PDF를 OCR 처리하고 문서 구조와 문장을 정리하여 **TTS에 적합한 EPUB3 전자책으로 변환하는 로컬 우선 데스크톱 도구**입니다.

주요 사용 목적은 개인이 소장한 책을 스캔하여 스마트폰·태블릿의 EPUB 리더에서 TTS로 듣는 것입니다. 특히 운전 중 장시간 청취하는 상황을 주요 사용 시나리오로 고려합니다.

## 핵심 목표

### 현재 실행 가능한 상태 (2026-09-08)

`CODEX_FIRST_PROMPT.md`의 초기 구현 범위인 PDF → 한국어 OCR → 원본 JSON →
기본 정리 → 검증된 EPUB3 변환을 구현했고, 이후 실제 스캔본 여러 권으로 검증하며
반복 머리글·꼬리글 탐지, PDF 텍스트 레이어 재사용, GPU 가속(PaddleOCR),
페이지 범위 지정, 여러 파일 배치 처리, GUI(드래그 앤 드롭 포함)까지 추가했습니다.
세션별 변경 이력은 [docs/CHANGELOG.md](docs/CHANGELOG.md), 남은 항목은
[docs/roadmap.md](docs/roadmap.md)를 참고하세요. 다른 작업자가 이어서 개발할 때는
[현재 사양 및 인수인계](docs/CURRENT_SPEC.md)를 먼저 확인하세요. 장시간 실제 도서 청취 검증은
아직 남아 있습니다.

설치 및 실행 (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
$env:EPUBCHECK_JAR = (Resolve-Path .tools/epubcheck-5.3.0/epubcheck.jar).Path
.\.venv\Scripts\scan2read convert book.pdf --tesseract 'C:\Program Files\Tesseract-OCR\tesseract.exe'
```

외부 도구는 별도 로컬 설치가 필요합니다.

Windows GUI 배포본은 [docs/WINDOWS.md](docs/WINDOWS.md)의 온라인 설치 방식을
사용합니다. 약 123MB의 설치 EXE가 기본 런타임을 포함하고, 설치 과정에서
CPU용 PaddleOCR·Kiwi·한국어 OCR 모델을 다운로드합니다. 설치 후 용량은 약
1.2GB이며 CUDA 라이브러리는 사용자가 GPU 가속을 선택할 때만 설치됩니다.

- [Tesseract 설치 안내](https://tesseract-ocr.github.io/tessdoc/Installation.html): `kor`, `eng` 언어 데이터 포함. PATH에 등록하면 `--tesseract` 생략 가능.
- [EPUBCheck 설치 안내](https://www.w3.org/publishing/epubcheck/docs/installation/): ZIP 전체를 풀고 Java 설치. JAR만 복사하면 필요한 라이브러리가 빠집니다. `EPUBCHECK_JAR` 또는 `--epubcheck`로 지정합니다.

기본 출력은 입력 옆의 동명 `.epub`입니다. `--output`, `--work-dir`, `--dpi`
(36~600, 기본 300), `--force`를 지원합니다. `--psm`은 기본 6(단일 본문 블록),
3 또는 4로 변경할 수 있습니다. `--language` 기본값은 `kor+eng`입니다.
`--reconstruct`는 PDF 텍스트 레이어의 단어 조각을 좌표로 한 줄로 묶은 뒤,
줄 길이·들여쓰기·간격과 로컬 Kiwi 형태소 분석을 함께 사용해 끊어진 본문을
보수적으로 연결합니다. 종결 문장, 제목, 목록은 경계로 유지하며 Raw OCR은
수정하지 않습니다. GUI의 "문맥·줄바꿈·문단 보정"이 같은 기능입니다.
`--columns 2`는 중앙 부근 여백을 찾아 좌우 단을 각각 PSM 6으로 읽는 실험 옵션입니다.
위쪽 제목은 큰 수직 여백이 확인될 때 별도 영역으로 읽습니다. 기본값은 1이며,
표·불규칙한 단·전폭 삽화가 섞인 책에는 보장하지 않습니다. IVP 5쪽 시험에서 제목과
일부 누락 문장은 개선됐지만 한글의 영문 오인식은 남아 있어 전체 책 변환 전 검토가 필요합니다.
상세 로그는 명령 앞의 `--debug`로 켭니다. `--pages 30-50`으로 전체가 아니라 지정한
페이지 범위(1부터 시작, 양끝 포함)만 처리해 그 범위만 담은 EPUB을 만들 수 있습니다.
OCR 캐시는 범위와 무관하게 페이지 단위로 공유되므로, 이후 다른 범위나 전체 책을
변환해도 이미 처리한 페이지는 재사용합니다.

PDF 페이지에 이미 추출 가능한 텍스트 레이어가 있으면(예: Word에서 내보낸 PDF)
`--text-layer auto`(기본값)가 해당 페이지의 OCR을 건너뛰고 그 텍스트를 그대로
사용합니다. 텍스트 레이어의 인코딩이 깨져 대체 문자·사용자 영역 문자·낱개
한글 자모가 나오는 경우에만 그 블록에 한해 페이지 이미지를 잘라 OCR로
보정합니다 — 맞춤법이나 낯선 단어를 임의로 고치지는 않습니다. 이미지 스캔처럼
텍스트 레이어가 없거나 페이지에 텍스트가 거의 없으면 기존처럼 OCR을 수행합니다.
항상 OCR만 쓰려면 `--text-layer off`를 지정합니다. 변환 없이 텍스트 레이어
비율만 미리 확인하려면 `scan2read inspect book.pdf`로 페이지 수와 텍스트
레이어가 감지된 페이지 수를 JSON으로 출력합니다.

`--remove-footnotes`는 페이지 하단에서 번호·기호로 시작하고 본문보다
작은 글자로 보이는 문단을 각주로 간주해 제거하는 실험적·opt-in 옵션입니다.
기본값은 끔이며, 위치와 글자 크기만으로 판단하므로 드물게 페이지 끝에 우연히
놓인 번호 목록을 지우거나 다른 형식의 각주를 놓칠 수 있습니다.

`--remove-parentheses`는 "지라(계2:5)"처럼 괄호로 묶인 성경 구절 인용 등을
제거하는 opt-in 옵션입니다. Raw OCR·Clean Text는 그대로 두고 최종 낭독용
텍스트에만 적용되는 TTS 전용 변환이라, 캐시된 clean JSON에는 원문이 그대로
남습니다. 한 문단 안에서 괄호 개수가 맞지 않으면(OCR 오인식 등) 그 문단은
안전하게 건드리지 않습니다.

`--engine paddle`은 NVIDIA GPU 가속을 지원합니다. `scan2read gpu-status`로 GPU
인식 여부와 설치 상태를 확인하고, `scan2read gpu-install`로 CUDA 빌드
(paddlepaddle-gpu, 약 2GB, PaddlePaddle 자체 패키지 서버에서 내려받음)를
설치합니다. 설치 후 `--gpu`를 붙이면 해당 페이지를 GPU로 처리합니다(예: RTX 3070
기준 페이지당 recognize 약 29초 → 약 1초). GPU와 CPU는 부동소수점 연산 차이로
극히 드물게 인식 결과가 미세하게 다를 수 있어 `--gpu` 사용 여부는 캐시 키에
포함되며, 기본 설치본은 CPU 전용으로 유지되어 GPU가 없는 PC의 설치 용량에는
영향이 없습니다. GPU 변환 중에는 별도 프로세스가 다음 미처리 페이지 하나를
미리 렌더링합니다. 실제 8페이지 반복 측정에서는 이미지와 OCR 결과를 유지하면서
렌더링+OCR 시간이 평균 23.3% 줄었습니다. 책과 PC 상태에 따라 개선 폭은 달라집니다.

중단 후 같은 명령을 다시 실행하면 완료된 OCR을 재사용합니다. `--force`는 새
세대 폴더에 OCR을 저장하여 기존 원본을 보존합니다. 손상된 원본 캐시는 자동
덮어쓰기하지 않고 오류로 중단하므로 필요하면 `--force`로 새 결과를 생성합니다.

`scan2read ocr-pages <file> --pages A-B ...`는 EPUB을 만들지 않고 그 페이지 구간만
OCR해서 캐시에 저장합니다. 캐시 키가 페이지 범위를 타지 않으므로(소스 SHA256·DPI·엔진·
text_layer 모드로만 결정) 겹치지 않는 구간을 여러 프로세스가 동시에 실행해도 안전하며,
이후 전체 범위로 `convert`를 실행하면 그 캐시를 그대로 재사용해 OCR 없이 EPUB만
조립합니다. GUI가 이 서브커맨드로 큰 책의 페이지 구간을 나눠 병렬 OCR합니다(아래
"동시 처리 개수" 참고). `scan2read gpu-usage`는 `nvidia-smi` 기반 실시간 GPU 사용률·
VRAM 사용량을 JSON으로 출력합니다.
원본 PDF·DPI·OCR 실행 파일·언어 모델·PSM이 바뀌면 캐시가 분리됩니다.
동일 작업 디렉터리의 동시 실행은 현재 지원하지 않습니다.

상하단 여백에서 같은 짧은 문자열이 가까운 3페이지 이상에 반복되면 머리글·꼬리글로
제거합니다. 본문 위치의 같은 표현과 큰 제목, 명시된 heading 블록은 보존합니다.
판정은 Clean Text에만 적용하며 원본 OCR은 유지합니다. 현재는 공백을 제외한 동일
문자열만 판정하므로 OCR 철자가 달라진 머리글은 남을 수 있습니다.

검증 실패는 명령 실패이며 최종 EPUB을 교체하지 않습니다. 페이지 처리 오류도
현재는 즉시 중단하고, 재실행 시 완료된 페이지부터 재개합니다.

테스트:

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
# 실제 OCR/EPUBCheck 통합 테스트도 실행하려면:
$env:SCAN2READ_TESSERACT = 'C:\Program Files\Tesseract-OCR\tesseract.exe'
$env:SCAN2READ_TEST_FONT = 'C:\Windows\Fonts\malgun.ttf'
$env:EPUBCHECK_JAR = (Resolve-Path .tools/epubcheck-5.3.0/epubcheck.jar).Path
.\.venv\Scripts\python -m unittest discover -s tests -v
```

실제 도구를 지정하지 않으면 통합 테스트 1개는 건너뜁니다. Windows에서 실제
통합 테스트를 포함한 21개 테스트가 통과했습니다. 자세한 구조는
[architecture](docs/architecture.md), 다음 작업은 [roadmap](docs/roadmap.md)를 참고하세요.

Scan2Read의 우선순위는 원본 책의 시각적 레이아웃을 완벽하게 복제하는 것이 아닙니다. 다음을 정확하게 복원하는 것을 우선합니다.

- 본문 내용
- 읽기 순서
- 문장
- 문단
- 장·절·소제목 구조
- 목차
- 페이지 번호 제거
- 머리글·꼬리글 제거
- TTS에 방해되는 OCR 오류 제거
- 자연스러운 연속 낭독

```text
Scan PDF
   ↓
OCR
   ↓
Document Reconstruction
   ↓
Text Cleanup
   ↓
TTS Optimization
   ↓
EPUB3
```

## 핵심 설계 원칙

OCR 원본 결과는 절대로 직접 수정하거나 덮어쓰지 않습니다.

```text
Raw OCR
    ↓
Clean Text
    ↓
TTS Text
```

- Raw OCR: OCR 엔진이 반환한 원본 결과
- Clean Text: 원문의 의미와 표현을 유지하며 구조 오류를 정리한 결과
- TTS Text: 낭독 편의를 위한 추가 변환 결과

예:

```text
Clean Text:
마 5:3-10

TTS Text:
마태복음 5장 3절에서 10절
```

## MVP 목표

첫 번째 개발 단계에서는 GUI를 만들지 않습니다.

```bash
scan2read convert book.pdf
```

또는

```bash
python -m scan2read convert book.pdf
```

정상 완료 후 `book.epub`이 생성되어야 합니다.

## MVP 필수 기능

1. PDF 입력
2. PDF 페이지 렌더링
3. 한국어 OCR
4. OCR 결과 저장
5. 페이지 번호 제거
6. 단순 머리글·꼬리글 제거
7. 물리적 줄바꿈 정리
8. 기본 문단 복원
9. EPUB3 생성
10. EPUB 유효성 검증
11. 중간 결과 캐시
12. 중단 후 재개

초기 구현에서는 M4B, TTS 음성 생성, 복잡한 표 복원, 세로쓰기, 고문헌, 복잡한 레이아웃을 제외합니다.

## 대상 입력 문서

- 한국어 단행본
- 가로쓰기
- 텍스트 중심
- 1단 편집
- 일반적인 책 스캔
- 흑백 또는 컬러 PDF
- 약 100~500페이지 규모

## 권장 기술 스택

- Python 3.12+
- PDF: PyMuPDF
- Image: Pillow / OpenCV
- OCR: PaddleOCR 또는 Tesseract (추상화 계층 필수)
- EPUB: EbookLib
- Validation: EPUBCheck

## 권장 프로젝트 구조

```text
scan2read/
├─ README.md
├─ AGENTS.md
├─ pyproject.toml
├─ .gitignore
├─ src/
│  └─ scan2read/
│     ├─ __init__.py
│     ├─ __main__.py
│     ├─ cli.py
│     ├─ config/
│     ├─ pdf/
│     ├─ image/
│     ├─ ocr/
│     ├─ document/
│     ├─ cleanup/
│     ├─ tts/
│     ├─ epub/
│     ├─ project/
│     └─ utils/
├─ tests/
│  ├─ fixtures/
│  ├─ unit/
│  └─ integration/
├─ samples/
└─ docs/
   ├─ architecture.md
   └─ roadmap.md
```

## 프로젝트 작업 디렉터리

```text
work/
└─ my-book/
   ├─ project.json
   ├─ source.pdf
   ├─ pages/
   ├─ raw_ocr/
   ├─ clean/
   ├─ tts/
   └─ output/
      └─ my-book.epub
```

## OCR 데이터 모델

```json
{
  "page": 12,
  "width": 2480,
  "height": 3508,
  "blocks": [
    {
      "id": "block-001",
      "type": "text",
      "bbox": [120, 210, 2200, 420],
      "text": "OCR result",
      "confidence": 0.96
    }
  ]
}
```

## 처리 파이프라인

```text
PDF
 ↓
Render
 ↓
Preprocess
 ↓
OCR
 ↓
Layout / Reading Order
 ↓
Clean
 ↓
TTS Optimize
 ↓
EPUB Build
 ↓
Validate
```

각 단계는 가능한 한 독립적으로 재실행할 수 있어야 합니다.

## Resume 및 Cache

500페이지 이상 책의 처리를 고려하여 완료된 페이지를 다시 처리하지 않습니다. 상태를 디스크에 기록하고, 중단 후 마지막 체크포인트부터 재개합니다.

## EPUB

출력은 Reflowable EPUB3을 기본으로 합니다. 최소 메타데이터로 title, author, language, publisher, ISBN, cover를 지원합니다.

## 테스트 전략

우선 테스트 대상:

- 페이지 번호 탐지
- 머리글 제거
- 줄바꿈 합치기
- 문단 분리
- OCR 캐시
- 중단 후 재개
- EPUB 생성
- EPUB 구조 검증

실제 저작권 도서 전체를 테스트 fixture로 넣지 않습니다.

## 로깅 및 오류 처리

- INFO / WARNING / ERROR / DEBUG 수준 구분
- 페이지 단위 실패는 가능하면 전체 중단 없이 기록 후 계속
- 사용자 메시지와 개발 로그 분리

## 개인정보 및 원본 보호

기본 동작은 로컬 처리입니다. PDF 또는 페이지 이미지를 외부 서비스로 자동 업로드하지 않습니다. 향후 AI API를 추가하더라도 원칙은 다음과 같습니다.

```text
PDF / Image → local only
OCR Text    → optional AI API
```

GUI의 `AI 기능 전체 사용`을 켜면 문단 경계, OCR 의심 단어, 띄어쓰기, 이상 문자, 본문 구조,
EPUB 목차, 괄호·음역 중복 표현 삭제를 각각 선택해 검사할 수 있습니다. "괄호·음역 중복
표현 삭제"는 로컬 `cleanup/parentheses.py`의 결정론적 괄호 제거(괄호 짝이 맞을 때만
전체 제거)와 달리, 문맥을 봐서 "정의(체다카)"처럼 앞뒤 낱말과 뜻이 같아 소리 내어 읽으면
반복되는 음역/원어 병기 구절만 골라 지운다 — OCR이 괄호 한쪽을 깨뜨려(흔히 히브리어·
그리스어 원문 근처에서 발생) 로컬 옵션이 아예 손대지 못하는 문단도 다룰 수 있다. 후보
문자열이 원문에 정확히 한 번만 나오고 문단 길이의 1/3을 넘지 않을 때만 적용하는 보수적
검증은 기존 `ocr_edits`와 같은 안전장치 철학을 따른다(`ai_enhance.py`의
`_apply_glosses`). 제공자는 OpenAI · Claude(Anthropic) ·
Gemini(Google) 중 책 전체에 하나를 선택하고, 모델을 고릅니다
(OpenAI: GPT-5.6 Luna/Terra · Claude: Fable 5.1, Opus 5, Sonnet 5, Haiku 4.5 ·
Gemini: 3.8 Flash, 3.6 Flash, 2.5 Pro/Flash/Flash-Lite). 단가는
`cleanup/ai_providers.py`의 `MODELS`에 있으며 선택한 모델의 요금이 GUI에 표시됩니다.
제공자별 기본 모델은 플래그십이 아니라 저비용·균형 모델로 지정돼 있습니다
(`DEFAULT_MODEL_FOR`). GPT-6 Astra와 GPT-5.6 Sol은 실측 결과 같은 작업에 Luna의
36배·16배 비용이 들어 목록에서 제외했습니다(재추가하려면 비용 대비 효과 재측정 필요).
모델 입력칸은 자유 입력이
가능해 목록에 없는 모델 ID로도 바꿀 수 있고, 그 경우 요금을 알 수 없어 해당 제공자의 가장
비싼 모델 단가로 보수적으로 추정하며 경고가 표시됩니다. PDF와 페이지 이미지는 전송하지 않고 필요한 OCR 텍스트만
보냅니다. API 키가 없거나 요청이 실패하면 기존 로컬 판정으로 계속 진행합니다. API 키는
제공자별로 각각 Windows 암호화 저장소를 통해 보관할 수 있습니다.

GUI는 PDF 페이지 수로 변환 전 입력·출력 토큰과 책당 예상 최대 비용을 표시합니다. 변환 중에는
API가 반환한 실제 토큰, 누적 USD 비용, 기능별 배분 사용량, 배치 진행률(완료/전체 묶음 수와
예상 남은 시간)을 갱신합니다. 책 한 권당 비용 한도를 설정하면 다음 요청이 한도를 넘을 가능성이
있는 시점부터 API 호출을 중단하고 로컬 처리로 전환합니다 — 이 예산은 여러 요청을 동시에 보낼
때도(문단 보정은 최대 3개 병렬) 미리 예약하는 방식이라 한도를 넘지 않습니다. 같은 문단·모델·
기능 조합은 여러 책과 재실행에 걸쳐 캐시되어 재요청 없이 재사용됩니다. 실제 내역은 작업
캐시의 `clean/ai_usage.json`, 문단 판정은 `clean/ai_context.json`, 나머지 보정은
`clean/ai_enhancements.json`에 기록합니다. Raw OCR은 변경하지 않습니다.

CLI에서는 `--ai-provider {openai,anthropic,google}`(기본값 openai), `--ai-model`,
제공자에 맞는 환경변수(`OPENAI_API_KEY`/`ANTHROPIC_API_KEY`/`GOOGLE_API_KEY`), `--reconstruct`,
필요한 `--ai-*` 옵션과 선택적인 `--ai-cost-limit-usd`를 사용합니다.

## Roadmap

- Phase 1: CLI MVP
- Phase 2: OCR 및 레이아웃 분석 개선
- Phase 3: TTS 최적화
- Phase 4: PySide6 기반 GUI
- Phase 5: 선택적 AI 보정
- Phase 6: M4B 오디오북 생성

## 성공 기준

300~500페이지의 일반적인 한국어 스캔 단행본을 입력하여 다음을 만족하면 MVP 성공으로 봅니다.

- EPUB 정상 생성
- EPUB Reader에서 정상 오픈
- 장시간 TTS 재생 가능
- 페이지 번호 반복 없음
- 반복 머리글 최소화
- 문장 중간의 불필요한 끊김 최소화
- 처리 중단 후 재개 가능

가장 중요한 품질 기준은 다음입니다.

> 운전하면서 화면을 보지 않고 장시간 들어도 내용 이해에 방해되는 오류가 충분히 적은가?
