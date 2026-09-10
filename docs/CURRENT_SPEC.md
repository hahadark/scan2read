# Scan2Read 현재 사양 및 인수인계

기준일: 2026-09-08

이 문서는 현재 실행 가능한 제품 상태와 다음 작업을 한곳에 정리한 인수인계 문서다.
새 작업자는 먼저 `AGENTS.md`와 이 문서를 읽고, 세부 이력은 `docs/CHANGELOG.md`를 확인한다.

## 제품 목표

Scan2Read는 한국어 단행본 PDF를 장시간 듣기 편한 reflowable EPUB3으로 변환하는
로컬 우선 Windows 애플리케이션이다. 시각적 원본 복제보다 OCR 정확도, 읽기 순서,
문장·문단 연결, 페이지 요소 제거와 연속 낭독 품질을 우선한다.

처리 데이터는 반드시 다음 순서를 유지한다.

```text
Raw OCR → Clean Text → TTS Text
```

- Raw OCR은 절대로 수정하거나 덮어쓰지 않는다.
- 원문 보정과 구조 복원은 Clean Text에 기록한다.
- 괄호 제거처럼 낭독 목적의 변환은 TTS Text에서만 수행한다.
- PDF와 페이지 이미지는 외부 API로 전송하지 않는다.

## 현재 구현된 처리 흐름

1. PDF 검사 및 페이지 단위 렌더링
2. PDF 텍스트 레이어 재사용 또는 PaddleOCR/Tesseract 실행
3. 페이지별 구조화 Raw OCR JSON 저장과 재개
4. 페이지 번호, 반복 머리글·꼬리글, 각주와 작은 OCR 잡음의 보수적 제거
5. 좌표 기반 줄 결합, 문단 복원, Kiwi 문맥·띄어쓰기 보정
6. 선택적인 AI 보정 (OpenAI/Claude/Gemini 중 선택)
7. 선택적인 TTS 전용 괄호 내용 제거
8. 제목 구조와 목차를 포함한 EPUB3 생성
9. EPUBCheck 검증 후에만 최종 파일 교체

OCR은 페이지별로 캐시되며 중단 후 같은 입력과 설정으로 실행하면 완료된 페이지를
재사용한다. GPU 처리에서는 다음 미처리 페이지 하나만 미리 준비해 메모리 사용을 제한한다.

## GUI 사양

현재 Tk 기반 GUI는 다음을 지원한다.

- 여러 PDF 추가, 선택 제거, 목록 비우기
- PDF 파일 또는 PDF가 바로 들어 있는 폴더의 드래그 앤 드롭
- 출력 폴더만 선택하고 파일명 규칙으로 결과 이름 생성
- `{name}`, `{folder}`, `{index:03d}` 파일명 규칙
- 여러 책 동시(최대 4개) 배치 변환과 파일별 상태 표시, 큰 책은 페이지 구간을 나눠 병렬 OCR
- 1단/2단, 페이지 범위, 텍스트 레이어 무시, 각주·괄호 제거
- 로컬 띄어쓰기와 문맥·줄바꿈·문단 보정
- NVIDIA GPU 감지와 선택적인 GPU 런타임 설치, 실시간 GPU 사용률·VRAM 표시
- 마지막 설정 저장
- 제공자별 API 키 연결 확인과 Windows DPAPI 암호화 저장(제공자마다 독립적인 키)
- 화면은 "변환"(파일 목록·시작/중단·로그) · "변환 설정"(출력·보정 옵션·GPU·동시 처리 개수) ·
  "AI 설정"(제공자·모델·키·기능·비용) 3개 탭으로 나뉜다

AI는 `AI 기능 전체 사용`을 마스터 스위치로 사용하며 아래 기능을 각각 켜고 끌 수 있다.

1. 문단 경계 검사
2. OCR 의심 단어 보정
3. 띄어쓰기 AI 재검사
4. 이상한 글자 탐지
5. 제목·본문·각주 분류
6. 장·절 구조 및 목차 감지
7. 괄호·음역 중복 표현 삭제

**2026-09-08 추가: 제공자·모델 선택.** 책 전체에 제공자(OpenAI/Anthropic Claude/Google
Gemini)와 모델을 하나씩 고른다(기능별로 다른 제공자를 쓰는 방식은 채택하지 않음 — 구현이
단순하고 비용 예측이 쉬움). 제공자 콤보박스는 읽기 전용, 모델 콤보박스는 자유 입력 —
`src/scan2read/cleanup/ai_providers.py`의 `MODELS` 레지스트리에 없는 임의의 모델 ID도
입력할 수 있다. 제공자를 바꾸면 그 제공자의 저장된 키로 API 키 입력칸이 자동으로 바뀌고,
모델은 그 제공자의 기본(저비용) 모델로 맞춰진다. 모델칸 아래에는 선택한 모델의 백만
토큰당 입력·출력 단가를 항상 표시하며(같은 제공자 안에서도 최대 50배 차이), 레지스트리에
없는 모델 ID를 입력한 경우에만 노란 경고로 바뀐다(`ModelSpec.verified=False`).

API 키가 없거나 연결에 실패하면 변환을 중단하지 않고 로컬 처리로 진행한다.

**2026-09-09 추가: 페이지 분할 병렬 OCR, GPU 사용률 표시, 탭 정리.** 사용자가 프로그램을
여러 개 띄워서 동시에 변환하면 GPU 사용량이 늘어나는 걸 직접 발견했다 — 각 `scan2read
convert` 서브프로세스가 `PaddleEngine.__init__`에서 독립된 PaddleOCR/CUDA 컨텍스트를
새로 로드하므로, 여러 프로세스가 각자 독립적인 GPU 컨텍스트로 병렬 실행된 것이었다. 이
메커니즘을 GUI가 자동으로 활용하도록 확장했다.

- **동시 처리 개수** ("변환 설정" 탭, 1~4, 기본 2): `Preferences.max_parallel_conversions`.
  값이 클수록 GPU 메모리를 그만큼 더 쓴다(프로세스마다 독립적으로 모델을 올리므로) —
  자동 감지·자동 조정은 하지 않고, 사용자가 아래 실시간 GPU 사용률을 보며 직접 조정한다.
- **페이지 분할**: 배치 시작 시 각 파일을 `min(동시 처리 개수, 총 페이지/15)`개의 연속
  페이지 구간으로 나누고(너무 잘게 쪼개면 프로세스당 PaddleOCR 모델 로딩 오버헤드가
  커지므로 구간당 최소 15쪽), 새 `scan2read ocr-pages --pages A-B` 서브커맨드로 구간마다
  독립된 프로세스를 띄워 OCR만 수행하고 캐시에 저장한다(EPUB을 만들지 않음). 캐시 키가
  페이지 범위를 포함하지 않고(`source_sha256`·DPI·엔진·text_layer 모드로만 결정) 원시
  OCR이 페이지별 독립 파일이라, 서로 겹치지 않는 구간을 여러 프로세스가 동시에 써도
  안전하다(`--force`를 쓰지 않는 한 `generation`이 항상 고정 문자열 `"initial"`이라는
  점에 의존 — GUI는 배치 변환에 `--force`를 쓰지 않는다). 한 파일의 모든 구간이 끝나면
  그 파일 전체 범위로 `scan2read convert`(EPUB 빌드까지)를 한 번 실행하는데, 이미 모든
  페이지가 캐시돼 있어 OCR 없이 곧장 문단 재구성·EPUB 빌드로 넘어간다.
- **작업 스케줄러** (`gui.py`): 파일별 OCR 구간 잡과 "최종 조립" 잡을 하나의 평평한 큐로
  관리하며, 항상 `동시 처리 개수`만큼 슬롯이 차 있도록 슬롯이 빌 때마다 큐에서 채운다.
  한 파일의 OCR 구간이 모두 끝나면 그 파일의 최종 조립 잡을 큐 맨 앞에 추가한다. 파일이
  여러 권이면 한 파일의 구간들과 다른 파일의 최종 조립이 같은 슬롯 풀을 통해 자연스럽게
  섞여 돈다. "동시 처리 개수"가 1이면 청크를 아예 만들지 않고 기존과 동일하게 파일마다
  `convert` 한 번만 실행한다(이 기능을 쓰지 않는 사용자는 동작 변화가 없다).
  페이지 수를 아직 확인하지 못한 파일(백그라운드 페이지 수 조회가 안 끝난 경우)도 청크
  없이 단일 최종 조립 잡으로 처리된다.
  - 진행률: 목록의 "상태" 칸에 그 파일의 완료 페이지 합계를 "OCR 320/554쪽"처럼 표시한다
    (각 구간 프로세스가 남기는 기존 `Rendering/OCR: n / 전체` 로그 형식을 그대로 재사용 —
    파이프라인 로그 포맷은 바뀌지 않았다). 전역 진행바는 "완료 파일 수/전체 파일 수"로
    의미가 바뀌었다.
  - 취소: `중단`을 누르면 활성 중인 모든 프로세스를 종료한다. 한 파일에 아직 끝나지
    않은 구간이 여러 개 있으면, 그 파일의 활성 잡이 **모두** 끝나야 "중단"으로 표시한다
    (다른 구간이 계속 도는 중에 성급하게 표시하지 않기 위해). 전체 활성 작업이 다 비면
    그제서야 아직 시작 안 한 나머지 파일들을 "취소"로 일괄 표시한다.
- **GPU 사용률 표시**: `ocr/gpu.py`의 `gpu_utilization()`이 `nvidia-smi
  --query-gpu=utilization.gpu,memory.used,memory.total`을 파싱한다. GUI는 GPU가
  감지된 경우에만 새 `scan2read gpu-usage` 서브커맨드를 3초 간격으로 서브프로세스 호출해
  "GPU 사용률 63% · VRAM 4.2/8.0GB"처럼 표시한다(패키지 의존성이 없는 조회라 기존
  `gpu-status`처럼 여러 번 불러도 부담이 적다).
- **탭 정리**: AI 제공자·모델 선택 기능이 추가되며 메인 화면이 너무 길어져 시작/중단
  버튼과 로그창이 화면 아래로 밀려 안 보이는 문제가 있었다. `ttk.Notebook`으로 "변환"
  (파일 목록·실행·로그) / "변환 설정"(출력·보정 옵션·GPU·동시 처리 개수) / "AI 설정"
  (제공자·모델·키·기능·비용)을 분리했다. 위젯 속성 이름은 바꾸지 않고 담기는 탭
  프레임만 바꿔서, 레이아웃과 무관한 기존 테스트는 대부분 그대로 통과한다. 창 기본
  크기를 1040x920에서 1000x700으로 줄였다.

관련 파일: `src/scan2read/pipeline.py`(`ocr_only`, `_ocr_pages`, `_settings_key`),
`src/scan2read/cli.py`(`ocr-pages`, `gpu-usage` 서브커맨드), `src/scan2read/ocr/gpu.py`
(`gpu_utilization`), `src/scan2read/gui.py`(작업 스케줄러, 탭 레이아웃).

**2026-09-09 추가: 괄호·음역 중복 표현 삭제(AI), sv-ttk 테마 적용.** 실제 책(히브리어
원어를 다루는 신학서)에서 사용자가 "정의(체다카)"처럼 원어를 한글로 음역해 괄호로 병기한
표현이 TTS로 들으면 같은 말이 반복되는 것처럼 들린다고 지적했다. 로컬 `remove_parenthetical`
(괄호 안 내용 제거)은 괄호 짝이 정확히 맞을 때만 전체 삭제하는 결정론적 규칙이라, 판단
없이 통째로 지우거나(짝이 맞을 때) 아예 손대지 않는다(짝이 안 맞을 때) 둘 중 하나만
가능하다 — 실제로 확인해 보니 이 책의 한 문단은 OCR이 괄호 하나를 놓쳐서(짝이
11:10으로 안 맞음) 로컬 옵션이 전혀 손대지 못하고 있었다.

- 새 AI 기능 "괄호·음역 중복 표현 삭제"(`AIOptions.glosses`)가 이 두 경우를 모두 다룬다:
  AI가 문맥을 보고 "바로 앞뒤 낱말과 뜻이 같아 반복되는 음역/원어 병기"만 골라 원문
  그대로(깨진 괄호 기호까지 포함) 부분 문자열로 지목하면, `AIEnhancer._apply_glosses()`가
  지운다. 안전장치는 기존 `ocr_edits`(오탈자 수정)와 다르다 — 삭제는 "after" 텍스트가
  없어 유사도 비율 비교가 의미가 없으므로, 그 부분 문자열이 원문에 **정확히 한 번만**
  나오고 **문단 길이의 1/3을 넘지 않을 때만** 적용한다. 로컬 사전 필터(`ai_filter.py`)는
  괄호 문자(`(`, `)`, 전각 포함)가 하나라도 있으면(한쪽이 깨졌어도) 이 문단을 AI로
  보낸다 — 로컬 결정론적 옵션이 정확히 못 다루는 그 경우를 겨냥한 필터.
- 정리 순서: `ocr_edits` → `glosses` 삭제 → `spacing_text` 적용. 같은 문단에서 glosses와
  spacing이 동시에 유효한 응답을 만들면, spacing_text 검증(공백 제외 원문과 일치해야
  적용)이 glosses 삭제 이후의 텍스트와 어긋나 spacing 쪽이 적용되지 않을 수 있다 — 기존
  ocr_edits+spacing 조합에도 이미 있던 동일한 보수적 한계(두 기능이 같은 문단을 서로
  다르게 바꾸면 더 보수적인 쪽만 남는다)를 그대로 물려받은 것이며, 이번에 새로 만든
  제약은 아니다.
- 관련 파일: `src/scan2read/cleanup/ai_enhance.py`(`AIOptions.glosses`,
  `_apply_glosses`), `src/scan2read/cleanup/ai_filter.py`(`_HAS_PAREN`),
  `src/scan2read/cleanup/parentheses.py`(공유 공백 정리 `tidy_whitespace`), CLI
  `--ai-glosses`, GUI "AI 설정" 탭의 7번째 기능 체크박스.

**GUI 테마**: 사용자가 "GUI가 너무 옛날거"라고 지적했다 — 확인해 보니 Windows 기본 ttk
테마인 "vista"가 이미 적용돼 있었지만, 이는 Windows 7~10 시절 스타일이라 Windows 11
기준으로는 여전히 예스럽다. 가벼운(순수 파이썬, 약 100KB) 오픈소스 테마 라이브러리
`sv-ttk`(Sun Valley, Windows 11 스타일)를 새 의존성으로 추가해 모든 ttk 위젯에
일괄 적용했다(`gui.py`, `Application.__init__` 맨 앞에서 `sv_ttk.set_theme("light",
root=window)`). `pyproject.toml`에 의존성 추가, `Scan2Read.spec`에
`collect_data_files('sv_ttk')`로 `.tcl`/`.png` 테마 파일을 프리징에 포함(순수 파이썬
분석만으로는 이 비-`.py` 에셋을 못 찾아 런처가 테마 파일을 못 찾는 오류를 냈을 것이다).

**후속 수정**: 실제로 재빌드한 exe를 실행한 사용자가 폰트가 이상하다고 지적했다.
`sv_ttk`의 `sv.tcl`이 만드는 8개 명명된 Tcl 폰트(`SunValleyBodyFont` 등)가 전부
"Segoe UI Variable"로 고정돼 있는데, 이 폰트의 한글 대체(fallback)가 이 PC에서 제대로
동작하지 않았다(트리뷰 행·헤딩, LabelFrame 캡션 등 sv_ttk가 직접 폰트를 지정한 곳만
영향받고, 나머지 위젯은 기존 `TkDefaultFont`를 써서 문제없었다). `gui.py`의
`_use_malgun_gothic(window)`가 `sv_ttk.set_theme()` 직후 이 8개 폰트 객체를 전부
"맑은 고딕"으로 재설정한다(굵은 계열은 `weight="bold"`로, 맑은 고딕엔 별도 Semibold
패밀리명이 없으므로).

**HiDPI 대응**: 사용자가 요청해 추가했다. PyInstaller로 만든 exe는 매니페스트에
DPI 인식을 선언하지 않아 기본적으로 "DPI 비인식" 상태로 실행되고, Windows가 이를
저해상도로 그린 뒤 확대해서 보여준다(흐릿하게 보이는 원인). `gui.py`의 `dpi_scale()`이
`ctypes.windll.shcore.SetProcessDpiAwareness(1)`(PROCESS_SYSTEM_DPI_AWARE, 구버전
Windows는 `SetProcessDPIAware()`로 폴백)을 호출해 이를 끄고, 실제 배율을
`GetScaleFactorForDevice(0)`로 읽어 100분율(150% → 1.5)로 반환한다. `main()`이
**Tk 창을 만들기 전에** 이 함수를 호출해야 한다(창이 생긴 뒤에는 DPI 인식 전환이
반영되지 않는다).

이 배율은 두 갈래로 쓰인다:
- 글꼴 크기·ttk 테마 여백처럼 "포인트" 단위인 값은 Tk가 `tk scaling` 값을 통해 알아서
  픽셀로 환산하므로, `Application.__init__`에서 `window.tk.call("tk","scaling",
  dpi_scale*96/72)`로 한 번만 설정하면 된다(96은 Tk가 "배율 1.0"으로 가정하는 기준
  DPI, 72는 포인트 정의).
- 창 크기(`geometry`/`minsize`), 트리뷰 `rowheight`·컬럼 너비, 레이블 `wraplength`처럼
  코드에 그대로 박힌 픽셀 값은 `tk scaling`을 안 타므로, `Application._px(value)`
  헬퍼(`round(value*self.dpi_scale)`)로 하나하나 곱해서 적용한다. 자잘한 `padx`/`pady`
  여백까지는 맞추지 않았다 — 몇 픽셀 차이는 눈에 안 띄지만, 위 값들을 안 맞추면 커진
  글꼴에 비해 창·컬럼이 작아 보이거나 잘리는 문제가 실제로 생긴다.
- 테스트에서는 `Application(window)`(기본 `dpi_scale=1.0`)로 만들면 기존 픽셀 값이
  그대로 나와 레이아웃 관련 기존 테스트가 안 깨진다. `tests/test_gui.py`의
  `DpiScaleTests`가 `ctypes.windll`을 모킹해 배율 계산·API 실패 시 1.0 폴백을 검사하고,
  `GuiTests`에 1.5배로 만든 별도 `Application` 인스턴스의 실제 창 크기·컬럼 너비를
  확인하는 테스트를 추가했다.

## AI 처리와 원문 보호

`src/scan2read/cleanup/ai_providers.py`의 `AIProvider` 프로토콜(`ocr/base.py`의
`OCREngine` 패턴과 동일)로 세 제공자를 추상화한다. `ai_context.py`/`ai_enhance.py`는
어느 제공자든 `provider.complete(instructions, input_json, schema, max_output_tokens)`
하나로 호출하며, 배치·필터·캐시·예산·재시도 로직은 제공자와 무관하게 동일하다.

- **OpenAI**: Responses API, `store: false`, `reasoning.effort: none`, strict JSON schema.
- **Anthropic (Claude)**: Messages API, 스키마를 하나의 tool `input_schema`로 등록하고
  `tool_choice`로 강제 호출해 구조화 JSON을 받는다(Claude는 OpenAI 방식의 별도
  "strict schema" 응답 모드가 없음).
- **Google (Gemini)**: `generateContent`, `responseMimeType: application/json` +
  `responseSchema`(OpenAI/Anthropic 스키마의 `additionalProperties`처럼 Gemini가
  지원하지 않는 키워드는 요청 전에 제거).

원문 보호 규칙(제공자와 무관하게 동일):

- 문단 경계 기능은 텍스트를 고치지 않고 `join: true/false`만 받는다.
- OCR 단어 수정은 신뢰도 0.9 이상, 짧은 단일 치환, 높은 문자열 유사도 등 로컬 검증을
  통과한 경우에만 적용한다.
- AI 띄어쓰기는 공백을 제외한 모든 글자가 원문과 동일할 때만 적용한다. 고칠 게 없으면
  전체 텍스트를 다시 돌려받는 대신 `null`(짧은 무변경 응답)을 받는다.
- 이상 문자 결과는 감사 기록이며 그 자체로 원문을 삭제하지 않는다.
- 제목 감지 결과는 EPUB heading과 목차에 반영한다.
- 모든 적용 전후 값은 감사 JSON에 남긴다(`source`가 `ai`/`cache`/`fallback` 중 하나).

모델별 요청 옵션: OpenAI는 추론 토큰이 출력 요금으로 청구되므로 기계적 재작성인 이 작업에는
추론을 최소로 요청한다. 다만 허용값이 모델마다 다르다 — 5.6 계열은 `none`을 받지만
`gpt-6-astra`는 거부하므로(400, 허용값 `low`/`medium`/`high`/`xhigh`/`max`) `low`를 쓴다.
`ModelSpec.reasoning_effort`에 모델별로 지정하고, 레지스트리에 없는 모델은 거부당할 값을
추측하는 대신 필드를 아예 생략한다.

요청 타임아웃은 300초다(`REQUEST_TIMEOUT`). 한 배치가 최대 32,000 출력 토큰을 요청할 수
있고 큰 모델은 그만큼 만드는 데 수 분이 걸린다 — 60초였을 때 실제 5쪽 배치에서
`gpt-5.6-sol`과 `gpt-6-astra`가 모두 타임아웃했고, 타임아웃은 `OSError`라 아래 규칙에 따라
그 책의 나머지 AI 보정 전체가 조용히 꺼졌다.

오류 처리: 연결/HTTP 오류(`OSError` 계열)는 그 책의 나머지 전체를 로컬 처리로 전환한다
(계속 실패할 가능성이 높으므로). 응답은 왔지만 파싱·검증에 실패한 경우
(`ValueError`/`KeyError`/`TypeError`/`JSONDecodeError`)는 그 배치만 로컬로 넘어가고
다음 배치는 새로 시도한다 — 실제 554쪽 책에서 첫 배치 단 한 번의 응답 형식 오류가 나머지
550쪽 전체를 조용히 로컬 처리로 바꿔버린 문제를 고친 것.

관련 파일:

- `src/scan2read/cleanup/ai_providers.py`: 제공자 추상화, 모델 레지스트리, 연결 확인
- `src/scan2read/cleanup/ai_context.py`: 문단 경계 판정
- `src/scan2read/cleanup/ai_enhance.py`: 나머지 선택 기능
- `src/scan2read/cleanup/ai_usage.py`: 예상량, 실제 비용, 비용 한도(모델별 단가)
- `src/scan2read/cleanup/ai_filter.py`: AI 호출 전 로컬 사전 필터
- `src/scan2read/cleanup/ai_cache.py`: 문단 단위 AI 결과 캐시
- `src/scan2read/project/credentials.py`: 제공자별 API 키 암호화 저장
- `src/scan2read/pipeline.py`: Clean Text 및 감사 결과 저장

## 토큰·비용 사양

`src/scan2read/cleanup/ai_providers.py`의 `MODELS`에 모델별 단가를 등록한다. 2026-09-09에
세 제공자의 현행 모델을 웹 검색으로 조사해 전부 등록했고, 입력·출력 단가는 모두 각
제공자가 공개한 2026년 9월 기준 값이다(`gpt-5.6-luna`는 이 프로젝트의 실제 API 사용으로도
확인). 캐시 입력 단가는 OpenAI·Anthropic은 공개값, Google은 Google이 2.5 Flash에 공개한
25% 비율로 계산한 값이다.

| 모델 | 백만 토큰당 입력 USD | 캐시 입력 | 출력 |
|---|---:|---:|---:|
| openai:gpt-5.6-terra | 2.00 | 0.20 | 12.00 |
| openai:gpt-5.6-luna (기본값) | 0.20 | 0.02 | 1.20 |
| anthropic:claude-fable-5-1 | 10.00 | 0.25 | 50.00 |
| anthropic:claude-opus-5 | 5.00 | 0.50 | 25.00 |
| anthropic:claude-sonnet-5 (기본값) | 3.00 | 0.30 | 15.00 |
| anthropic:claude-haiku-4-5-20251001 | 1.00 | 0.10 | 5.00 |
| google:gemini-3.8-flash | 0.75 | 0.1875 | 3.75 |
| google:gemini-3.6-flash | 1.50 | 0.375 | 7.50 |
| google:gemini-2.5-pro | 1.25 | 0.3125 | 10.00 |
| google:gemini-2.5-flash (기본값) | 0.30 | 0.075 | 2.50 |
| google:gemini-2.5-flash-lite | 0.10 | 0.025 | 0.40 |

주의: `gemini-3.8-flash`는 도입가이며 2027-01-01에 2배로 오를 예정이다. Claude Fable
5.1의 캐시 읽기만 입력가의 10%가 아닌 2.5%다(Anthropic이 인하).

**`gpt-6-astra`와 `gpt-5.6-sol`은 의도적으로 목록에서 제외했다.** 실제 5쪽 측정에서
같은 기계적 정리 작업에 Luna의 각각 36배·16배 비용이 들었고(아래 "모델별 실측 비용" 참조),
품질 이득이 그 차이를 정당화하지 못한다고 판단했다. 실수로 빠진 게 아니므로 다시 넣으려면
비용 대비 효과를 새로 측정해야 한다. 사용자가 모델칸에 직접 ID를 입력하면 여전히 사용은
가능하되 미등록 모델로 취급된다.

모델별 실측 비용 (2026-09-09, "고대 근동 문화" 100~104쪽 5쪽, AI 기능 6개 전부 켬,
캐시된 OCR 재사용, AI 결과 캐시는 비운 상태):

| 모델 | 실제 비용 | 입력/출력 토큰 | Luna 대비 |
|---|---:|---|---:|
| gpt-5.6-luna | $0.0048 | 5,911 / 3,436 | 1x |
| gpt-5.6-terra | $0.0613 | 5,706 / 4,595 | 13x |
| gpt-5.6-sol | $0.1712 | 5,740 / 4,749 | 36x |
| gpt-6-astra | (완주 실패) | — | — |

Sol/Astra 수치는 60초 타임아웃으로 중단되기 전 측정한 값이라 Sol은 초기 측정치를,
Astra는 완주 기록이 없다. 5쪽 기준 차이가 이 정도면 554쪽 책 한 권에서는 Luna $0.5 대
Sol $19 수준으로 벌어진다.

같은 제공자 안에서도 단가가 최대 50배 차이 나므로, 제공자별 기본 모델은 플래그십이 아니라
저비용·균형 모델로 명시적으로 지정한다(`DEFAULT_MODEL_FOR`). 딕셔너리 순서상 첫 모델을
기본값으로 쓰면 제공자를 바꾸는 것만으로 가장 비싼 모델이 조용히 선택되기 때문이다.
레지스트리에 없는 모델 ID를 직접 입력하면 그 제공자의 **최악값**으로 근사한다 — 입력·캐시·
출력 단가를 각각 따로 최댓값으로 잡는다(가장 비싼 입력 단가와 가장 비싼 출력 단가가 서로
다른 모델일 수 있어서. 예: Google은 입력 최고가 `gemini-3.6-flash`, 출력 최고가
`gemini-2.5-pro`). 한도의 목적이 과다 지출 방지이므로 과대 추정은 일찍 멈추는 것으로
끝나지만 과소 추정은 조용히 초과 지출로 이어지기 때문이다. 이 경우 GUI에 경고가 표시된다.

GUI 표시:

- 변환 전: 선택한 PDF의 페이지 수와 활성 기능을 기준으로 예상 입력·출력 토큰 표시
- 변환 전: 배치 중 책 한 권의 예상 최대 비용 표시
- 변환 중: 현재 책의 실제 누적 입력·출력 토큰과 USD 비용 표시
- 변환 중: 기능별 요청 횟수, 배분 입력·출력 토큰과 비용 표시
- 완료 후: 최종 실제 사용량 유지

변환 전 값은 OCR 전 페이지 기반 보수적 추정치이며 청구 금액이 아니다. 실제 총사용량은
각 제공자의 응답을 `AIProvider.complete()`가 `input_tokens`/`output_tokens`/
`cached_input_tokens`로 정규화한 값을 그대로 쓴다(OpenAI는 `usage.input_tokens_details.
cached_tokens`, Claude는 `usage.cache_read_input_tokens`, Gemini는 캐시 개념이 없어
항상 0). 여러 기능은 비용과 지연을 줄이기 위해 한 요청에 함께 담는다. 따라서 기능별
토큰은 중복 합산하지 않고 활성 기능 사이에 배분한 값이며, 전체 토큰과 비용만 API가
반환한 정확한 총계다.

책 한 권당 비용 한도는 USD로 저장한다. 빈 값은 제한 없음이며 0은 API 요청을 하나도
허용하지 않는다. 각 API 호출 직전에 (지시문+입력 텍스트)의 UTF-8 바이트 수와
`max_output_tokens`로 해당 호출의 보수적 최대 비용을 계산해 **미리 예약**한다
(`AICostBudget.reserve()`, 락으로 보호됨) — 문단 보정은 최대 3개 요청을 동시에 보낼 수
있어서, 예약 없이 단순히 확인만 하면 두 스레드가 동시에 한도를 통과해 합쳐서 한도를
넘기는 경쟁 조건이 생길 수 있었다. 현재 누적 비용+예약분이 한도를 넘을 수 있으면 호출하지
않고, 해당 책의 나머지 작업을 로컬 처리로 전환한다(연결 오류일 때만; 개별 배치의 응답
오류는 그 배치만 로컬로 넘어감). 배치 변환에서는 책마다 예산 관리자를 새로 생성하므로
한도가 각 책에 독립적으로 적용된다.

저장 파일:

```text
clean/ai_usage.json          실제 총 토큰, 비용, 한도, 기능별 사용량
clean/ai_context.json        문단 경계 판정 감사 기록
clean/ai_enhancements.json   다른 AI 보정의 전후 및 적용 기록
```

CLI 옵션은 `--ai-cost-limit-usd AMOUNT`다. 제공자·모델은 `--ai-provider
{openai,anthropic,google}`(기본값 openai)와 `--ai-model ID`로 지정하며, 각 제공자는
서로 다른 환경변수(`OPENAI_API_KEY`/`ANTHROPIC_API_KEY`/`GOOGLE_API_KEY`)에서 키를
읽는다. GUI 설정은 `%LOCALAPPDATA%\Scan2Read\settings.json`, API 키는 별도의 DPAPI
암호화 파일에 제공자별로 독립된 항목(`{"version":2,"keys":{"openai":{...},
"anthropic":{...},"google":{...}}}`)으로 저장하며, 이전 단일 키 형식 파일을 만나면
자동으로 OpenAI 키로 마이그레이션한다.

## 현재 API 성능 특성과 다음 작업

사용자가 실제 변환에서 API 요청이 예상보다 느리다고 확인했다. 이전에 파악한 원인은
다음과 같다.

- 문단 경계 요청은 애매한 경계를 최대 32개씩 묶어 순차 실행한다.
- 나머지 보정은 문단 최대 12개씩 묶어 순차 실행한다.
- AI 띄어쓰기는 보정된 문단 전체를 응답받아 출력 토큰과 지연이 가장 크다.
- 동시 요청 처리가 아직 없다.

**완료됨 (2026-09-08): 로컬 사전 필터와 AI 결과 캐시**

- `cleanup/ai_filter.py`의 `needs_ai_review(text, kind, options)`가 `pipeline.py`에서
  `ai_enhancer.enhance()` 호출 전에 문단을 거른다. 활성 기능별로 신호가 있을 때만 보낸다:
  이상한 글자(`anomalies`)는 `pdf/text_layer.py`의 기존 손상 문자 판정을 그대로 재사용,
  OCR 단어(`ocr_words`)는 한글에 라틴/숫자가 공백 없이 붙거나 같은 글자가 4번 이상
  반복되는 경우, 띄어쓰기(`spacing`)는 공백 없는 한글이 12자 이상 이어지는 경우, 구조·목차
  (`structure`/`headings`)는 이미 `heading`으로 분류됐거나 60자 이하이면서 종결 부호로
  끝나지 않는 경우다. 필터 자체는 원문을 절대 수정하지 않으며, 활성 기능이 없으면 항상
  건너뛴다. 어느 기능도 신호를 못 찾으면 로컬(비-AI) 텍스트를 그대로 유지한다 — 필터를
  통과하지 못해 생기는 위험은 품질 저하일 뿐 정확성 손상이 아니다.
- `cleanup/ai_cache.py`의 `AIResultCache`가 문단 단위로 결과를 캐시한다. 키는
  `cache_key(model, features, text)`로, 모델·`SCHEMA_VERSION`(프롬프트/스키마가 바뀌면
  올려서 예전 캐시를 자동 무효화)·활성 기능 집합·문단 원문의 해시다. `AIEnhancer`가
  배치를 만들기 전에 각 문단을 캐시에서 조회해 캐시 적중분은 API 호출 없이 즉시 적용하고
  (`감사 기록 source: "cache"`), 캐시 미스만 실제로 API에 보낸 뒤 응답을 저장한다. 책마다
  독립된 `AICostBudget`과 달리 캐시는 `work-dir/_ai_cache/`에 저장되어 여러 책과 재실행에
  걸쳐 공유된다.
- CLI는 `--work-dir` 아래 `_ai_cache`를 자동으로 구성해 `AIEnhancer`에 전달한다
  (`cli.py`). GUI는 CLI 서브프로세스를 통해 동일하게 적용받으며 별도 변경이 필요 없었다.
- 테스트: `tests/test_ai_filter.py`, `tests/test_ai_cache.py`, `tests/test_ai_enhance.py`에
  캐시 재사용·교차 인스턴스 재사용 케이스 추가, `tests/test_pipeline.py`에 평범한 문단은
  전혀 보내지 않고 의심 문단만 `ai_enhancer.enhance()`에 도달하는 종단 간 테스트 추가.

**추가 완료됨 (2026-09-08): 배치 확대, 병렬 요청, 짧은 무변경 응답**

- `AIEnhancer`의 기본 `batch_size`를 12에서 24로 늘렸다(생성자 인자로 24~32
  사이에서 조정 가능).
- `max_parallel`(기본 3) 개의 배치를 `concurrent.futures.ThreadPoolExecutor`로 동시
  전송한다. `AICostBudget`에 `reserve()`/`record(reserved=...)`를 추가해 락으로 보호되는
  예약 방식을 구현했다 — 각 배치는 전송 *전에* 자신의 보수적 최대 비용을 예약하므로, 여러
  스레드가 동시에 확인-후-호출 틈새로 한도를 넘기는 경쟁 조건이 불가능하다. 예약이 거부되면
  즉시 `disabled=True`로 전환하고, 이미 시작된 요청은 끝까지 완료하되 아직 시작하지 않은
  배치만 새로 전송하지 않는다. 기존 `can_call()`(예약 없이 한 번에 하나씩만 호출하는
  `ai_context.py`의 순차 경로용)은 그대로 유지된다.
- 응답 스키마에서 `spacing_text`를 nullable로 바꿨다(`{"type":["string","null"]}`,
  여전히 required). 프롬프트가 "띄어쓰기를 고칠 필요가 없으면 전체 문장을 다시 쓰지 말고
  null을 반환하라"고 지시하므로, 변경이 없는 문단은 전체 텍스트를 그대로 반환하는 대신
  `null`이라는 짧은 값만 반환할 수 있다 — 출력 토큰·지연이 가장 컸던 부분을 직접 겨냥한
  변경이다. `ocr_edits`/`anomalies`는 원래부터 빈 배열로 "변경 없음"을 표현했고, `kind`는
  `"unchanged"` enum 값이 이미 있었으므로 추가 변경이 필요 없었다.
- `AIResultCache.set()`의 임시 파일명을 `uuid4()` 기반으로 바꿔, 같은 문단 텍스트가 서로
  다른 두 병렬 배치에 동시에 등장하는 드문 경우에도 캐시 파일 쓰기 경쟁이 나지 않게 했다.
- 테스트: `tests/test_ai_usage.py`에 `reserve`/`record` 예약 테스트 3개,
  `tests/test_ai_enhance.py`에 기본 배치 크기, null spacing_text, 실제 동시 실행 확인(스레드
  세이프 카운터로 최대 동시 실행 수 측정), 공유 예산이 병렬 상황에서도 한도를 넘지 않는지
  확인하는 테스트 4개 추가. 전체 191개 테스트 통과(스레딩 관련 테스트 포함 3회 반복 실행으로
  불안정성 없음 확인).

**실제 책으로 검증됨 (2026-09-08)**: 저장된 API 키로 "기독교 위험한 사상 1"(캐시된
100~120쪽)을 실제 변환했다.

- 5쪽(문단 30개): 로컬 필터가 13개를 걸러 **17개만 GPT 전송**, 전부 배치 1개·API 호출
  1번에 처리됨. 실제 비용 $0.0014 — 사전 보수적 추정치($0.0279)의 1/20. 13개 문단에
  실제 띄어쓰기 보정 적용, 5개 문단이 제목으로 재분류됨. EPUBCheck 통과.
- 21쪽(100~120쪽 전체): 배치 2개로 나뉨(문단 수가 batch_size=24를 넘음), 기능별 요청
  2회씩, 실제 비용 $0.0051 — 상한 $0.3의 1.7%. EPUBCheck 통과.
- 두 실행 모두 `ai_usage.json`에 요청 수·비용이 정상 기록됨을 확인.

**완료됨 (2026-09-08): API 단계 진행률 표시**

- `AIEnhancer`(병렬 배치)와 `AIContextJoiner`(순차 배치) 둘 다 새
  `progress` 콜백 인자를 받는다. 매 배치가 끝날 때마다(그리고 시작 전 0/N 한 번)
  `{"stage": "ai_enhance"|"ai_context", "completed_batches", "total_batches",
  "elapsed_seconds", "estimated_remaining_seconds"}`를 보고한다. 남은 시간은 지금까지
  완료된 배치의 평균 소요 시간으로 추정한다.
- 병렬 실행 중에도 진행률이 뒤섞이지 않도록, 배치 완료 카운트 증가와 콜백 호출을 같은
  잠금 구간 안에서 실행한다 — 잠금을 풀고 나서 콜백을 부르면 두 스레드가 어느 쪽 콜백을
  먼저 실행할지 OS 스케줄러에 달려 있어 완료 개수가 뒤바뀐 순서로(예: 2 다음 1) 보고될
  수 있다. 초기 테스트에서 이 순서 문제를 실제로 겪은 뒤 고쳤다.
- CLI가 `SCAN2READ_AI_PROGRESS {json}` 줄을 표준출력에 출력한다(`SCAN2READ_AI_USAGE`와
  같은 방식). GUI는 이를 파싱해 `문단 경계 검사 진행률: 2/2 묶음` 형태로 새 상태 줄에
  표시한다(로그 창에는 원본 줄이 노출되지 않음).
- 테스트: `tests/test_ai_enhance.py`·`tests/test_ai_context.py`에 진행률 콜백 테스트
  추가(0/N 초기 보고, 순서 보장, 배치 없을 때 0/0), `tests/test_gui.py`에 GUI 표시·로그
  파싱 테스트 추가.

**완료됨 (2026-09-08): AI 제공자 선택 (OpenAI/Claude/Gemini)**

- 새 `cleanup/ai_providers.py`가 `src/scan2read/ocr/base.py`의 `OCREngine(Protocol)`과
  같은 패턴으로 `AIProvider` 추상화를 도입했다. `ai_context.py`/`ai_enhance.py`는 더 이상
  벤더별 요청·응답 형식을 몰라도 되며, `provider.complete(instructions, input_json,
  schema, max_output_tokens) -> ProviderResponse`만 호출한다. 배치·로컬 사전 필터·캐시·
  예산 예약·재시도 분류·진행률 보고는 전부 그대로 유지된다.
- `OpenAIProvider`(기존 `/v1/responses` 로직을 그대로 이관), `AnthropicProvider`
  (Messages API, 강제 도구 호출 `tool_choice:{"type":"tool","name":"emit_result"}`로
  구조화 JSON을 받음 — Claude에는 OpenAI 같은 별도 strict-JSON 응답 모드가 없다),
  `GoogleProvider`(`generateContent` + `responseMimeType:"application/json"` +
  `responseSchema`, Gemini가 지원하지 않는 `additionalProperties` 키워드는 제거)로
  세 벤더를 구현했다.
- `ai_providers.MODELS` 레지스트리: 처음에는 `gpt-5.6-luna`만 확인된 값이고 나머지는
  추정값이었으나, 2026-09-09에 세 제공자의 현행 모델 13종을 웹 검색으로 조사해 실제
  공개 단가로 전부 교체했다(위 "토큰·비용 사양" 표 참조). 이제 레지스트리 모델은 전부
  `verified=True`이고, `verified=False`는 사용자가 직접 입력한 미등록 모델 ID에만
  적용된다 — `resolve_model()`이 그 제공자의 가장 비싼 모델 단가로 근사하고 GUI가
  경고를 띄운다(모델 입력칸은 자유 입력 가능).
- 제공자별 API 키는 Windows DPAPI로 암호화해 저장하되, 파일 하나에 제공자별로 분리된
  항목을 둔다(`credentials.py`, 이전 단일 키 형식은 자동으로 OpenAI 키로 마이그레이션).
- GUI(`gui.py`)에 제공자 콤보박스(OpenAI/Claude(Anthropic)/Gemini(Google))와 모델
  콤보박스(자유 입력 가능)를 추가했다. 제공자를 바꾸면 그 제공자의 저장된 키를 다시
  불러오고, 모델 유효성 확인(`resolve_model().verified`)에 따라 경고 라벨을 표시한다.
  "연결 확인" 버튼은 선택한 제공자·모델로 `ai_providers.check_access()`를 호출한다
  (OpenAI/Google은 무료 GET 조회, Anthropic은 무료 인증 확인 엔드포인트가 없어 최소
  비용의 POST 완료 요청 1회 사용).
- CLI(`cli.py`)에 `--ai-provider`/`--ai-model` 플래그를 추가했다.
- 이 세션에서 실제 API 키로 검증한 것은 OpenAI(`gpt-5.6-luna`)뿐이며, Claude·Gemini는
  단위 테스트(가짜 transport)로만 확인했다 — 실제 키가 생기면 모델 ID·단가를 재확인해야
  한다.
- 테스트: 새 `tests/test_ai_providers.py`(15개, 세 제공자 요청 형식·응답 파싱·레지스트리·
  `check_access`), `tests/test_ai_context.py`/`tests/test_ai_enhance.py`/
  `tests/test_ai_usage.py`/`tests/test_credentials.py`/`tests/test_cli.py`/
  `tests/test_gui.py`에 provider 생성자·GUI 제공자 전환·CLI 플래그 테스트 반영.

다음 개발 우선순위:

1. ~~로컬 사전 필터~~ (완료)
2. ~~AI 결과 캐시~~ (완료)
3. ~~통합 보정 배치 24로 확대~~ (완료, 24~32 범위에서 추가 조정 가능)
4. ~~2~3개 요청 병렬 실행과 공유 예산 잠금~~ (완료)
5. ~~변환 로그에 API 단계 진행률과 예상 남은 시간 추가~~ (완료)
6. ~~AI 제공자 선택 (OpenAI/Claude/Gemini)~~ (완료. 2026-09-09에 세 제공자 현행 모델
   13종의 공개 단가를 조사해 반영했고, 실제 변환 검증은 OpenAI만 마쳤다)
7. ~~파일 간·페이지 구간 간 병렬 OCR, GPU 사용률 표시, GUI 탭 정리~~ (완료, 2026-09-09.
   단위 테스트로만 검증 — 실제 여러 프로세스 동시 GPU 사용은 사용자가 원래 관찰한
   현상이지만, 이 GUI 스케줄러를 통한 재현은 아직 실제 책으로 확인 못 함)
8. ~~괄호·음역 중복 표현 삭제(AI), GUI sv-ttk 테마 적용~~ (완료, 2026-09-09. 실제 API
   호출로 검증하지 않고 단위 테스트로만 확인)
9. ~~HiDPI 대응~~ (완료, 2026-09-09. 실제 고해상도 모니터에서 직접 확인은 못 했다 —
   스크린샷 권한이 거부돼 헤드리스 테스트로만 검증)

API 성능 개선 항목 5개 모두 구현·테스트·실제 책 검증까지 마쳤다. 다만 실제 검증은 21쪽
규모라 배치 2개까지만 확인했고, 3개 이상 배치가 동시에 진행되는 진짜 대규모 병렬 상황은
아직 실제 책으로 못 봤다 — 필요하면 더 큰 페이지 범위로 추가 검증 가능.

## 테스트와 현재 상태

전체 테스트 명령:

```powershell
$env:PYTHONPATH = "src"
.\.tools\paddle-env\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

2026-09-09 현재 273개 통과, 실제 외부 OCR 환경 테스트 1개는 환경변수가 없으면 건너뛴다.
`tests/test_ai_usage.py`가 단가, 캐시 입력 비용, 기능별 무중복 배분, 호출 전 비용 차단과
변환 전 추정치를 검사하고, `tests/test_ai_providers.py`가 OpenAI/Anthropic/Google 세
제공자의 요청 형식과 응답 파싱을 검사한다. `tests/test_pipeline.py`의 `OcrOnlyTests`가
페이지 구간을 나눠 `ocr_only()`로 채운 캐시를 이후 `convert()`가 그대로 재사용하는지
확인하고, `tests/test_gui.py`가 청크 스케줄러(슬롯 채우기, 취소 순서, 진행률 집계)를
검증한다. `tests/test_ai_enhance.py`가 괄호·음역 삭제의 안전장치(정확히 한 번만 등장,
문단 길이 1/3 이내)를 검사한다.

현재 사용자가 실행하는 개발 빌드:

```text
C:\Users\Administrator\Documents\PDF to tts\build\Scan2Read\Scan2Read.exe
```

이 실행 파일은 2026-09-09 10:01에 HiDPI 대응 최종본으로 다시 빌드했고
(`--distpath build/launcher` → `dist/Scan2Read` 동기화), GUI 기동과 exe 바이트코드
안에 `dpi_scale`/`SetProcessDpiAwareness`/`GetScaleFactorForDevice`/`_px`가 실제로
들어있는지 확인했다.

**주의**: `Scan2Read.spec`은 `scan2read` 패키지 전체를 exe의 PYZ에 넣는다. 따라서 GUI
프로세스는 `app/scan2read`가 아니라 **빌드 시점에 박제된 사본**을 실행한다(`app/scan2read`는
CLI 서브프로세스 전용). `gui.py`뿐 아니라 `cleanup/` 등 GUI가 임포트하는 모든 코드가
바뀌면 런처를 다시 빌드해야 하며, 안 그러면 GUI만 조용히 옛 코드로 돈다.

사용자가 명시적으로 요청하기 전에는 설치 파일을 다시 만들지 않는다. 현재 작업은
실행 가능한 개발 빌드에 집중한다.

주의: PyInstaller 기본 출력 경로 `dist/Scan2Read`는 기존 스테이징 디렉터리를 지울 수 있다.
GUI 실행 파일을 다시 만들 때는 `docs/CHANGELOG.md`의 `Process notes for whoever builds next`를
먼저 확인하고, 실행 중인 `Scan2Read.exe`를 임의로 종료하지 않는다.

## 주요 제한

- AI 보정은 현재 느리며 특히 모든 기능과 AI 띄어쓰기를 함께 켠 긴 책에서 두드러진다.
- AI 비용의 변환 전 값은 추정치다. 실제 값과 하드 한도 판정은 API usage를 사용한다.
- 단가는 2026-09-09 기준 공개값이다. 제공자가 요금을 바꾸면 한도 판정이 어긋나므로
  실제 비용이 예상과 크게 다르면 `MODELS`를 다시 확인해야 한다(특히 `gemini-3.8-flash`는
  2027-01-01에 2배 인상 예정).
- 실제 API 키로 변환까지 검증한 제공자는 OpenAI뿐이다. Anthropic·Google 경로는 가짜
  transport 단위 테스트로만 확인했다.
- 동시 처리 개수를 올리면 GPU 메모리 사용량이 그만큼 배로 늘어난다(자동 조정 없음).
  실제 GPU 메모리가 부족하면 개별 `ocr-pages` 프로세스가 실패해 그 파일이 "실패"로
  표시될 수 있다 — 실시간 GPU 사용률 표시를 보며 사용자가 직접 값을 낮춰야 한다.
- 페이지 분할 병렬 OCR과 청크 스케줄러는 단위 테스트로만 검증했고, 실제 여러 프로세스가
  동시에 GPU를 쓰는 상황(사용자가 원래 관찰한 현상)을 이 스케줄러를 통해 실제 책으로
  재현·측정하지는 않았다.
- "괄호·음역 중복 표현 삭제"는 실제 API 호출로 검증하지 않고 가짜 transport 단위
  테스트로만 확인했다 — AI가 문맥을 얼마나 정확히 판단하는지(과다 삭제·과소 삭제)는
  실제 책으로 확인이 필요하다.
- `sv-ttk`가 새 필수 의존성이 됐다(`pyproject.toml`). 개발 venv(`.tools/paddle-env`)와
  PyInstaller 빌드 venv(`.venv`) 양쪽에 설치해야 하며, `Scan2Read.spec`이
  `collect_data_files('sv_ttk')`로 `.tcl`/`.png` 테마 파일을 프리징에 포함하지 않으면
  런처가 테마 파일을 찾지 못한다.
- HiDPI 대응은 창 크기·트리뷰·wraplength 등 주요 픽셀 값만 배율을 곱했고, 위젯 사이
  자잘한 `padx`/`pady` 여백까지는 맞추지 않았다 — 고배율에서 여백이 상대적으로 약간
  좁아 보일 수 있으나 잘림·겹침 수준은 아니다. 실제 고해상도(150%/200%) 모니터에서
  직접 확인하지 못했고 헤드리스 테스트(픽셀 값이 실제로 배율만큼 커지는지)로만
  검증했다.
- 문단이 1,600자를 넘으면 현재 AI 통합 보정에서 건너뛴다.
- 제목·본문·각주 분류 결과 중 제목은 EPUB 구조에 반영하지만, AI가 `footnote`로 분류했다는
  이유만으로 본문을 자동 삭제하지 않는다.
- 복잡한 표, 세로쓰기, 잡지형 다단 편집과 완벽한 각주 복원은 MVP 범위 밖이다.
- 저작권 도서 전체를 테스트 fixture나 저장소에 추가하지 않는다.
