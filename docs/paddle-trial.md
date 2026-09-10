# PaddleOCR 로컬 비교 실행

기본 엔진은 변경하지 않았다. 선택적 어댑터 `ocr/paddle.py`와 비교 스크립트를
추가했고 대형 의존성은 `.tools/paddle-env`에만 설치했다.

검토한 공식 자료:
- https://huggingface.co/PaddlePaddle/korean_PP-OCRv5_mobile_rec
- https://www.paddleocr.ai/main/en/quick_start.html
- https://www.paddlepaddle.org.cn/documentation/docs/en/install/index_en.html

PaddleOCR 및 한국어 모델은 Apache-2.0이다. Windows/macOS 지원 설치 안내가
제공되며 이번 실행은 Windows Python 3.12 CPU 환경이다. macOS 실측은 하지 않았다.
확인한 버전: PaddleOCR 3.7.0, PaddlePaddle 3.3.1, PaddleX 3.7.2.

설정: PP-OCRv5_mobile_det + korean_PP-OCRv5_mobile_rec, CPU, MKLDNN 비활성화,
회전/펴기 비활성화, 기존 300 DPI 렌더링 및 TwoColumnEngine 사용.
모델 가중치 다운로드만 네트워크를 사용하며 입력 PDF/이미지는 로컬 predict로 처리한다.

```powershell
python -m venv .tools/paddle-env
.\.tools\paddle-env\Scripts\python -m pip install paddlepaddle==3.3.1 paddleocr==3.7.0 -e .
.\.tools\paddle-env\Scripts\python scripts/trial_paddle.py
```

스크립트는 기존 로컬 5페이지 샘플을 입력으로 사용하며 별도 `work/ivp-paddle`에
원본 OCR을 보관한다. 정리 단계는 기존 반복 머리글 제거와 동일하다.
출력은 `output/ivp-sample/ivp-pages-30-34-paddle.epub`이다.
현재 시험용 캐시 식별자는 버전과 모델 이름을 사용하므로, 모델 파일을 직접 바꾸면
새 작업 경로로 시험해야 한다. 일반 CLI 기본 엔진 전환은 아직 하지 않았다.
