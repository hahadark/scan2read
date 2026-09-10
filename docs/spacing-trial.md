# Kiwi 띄어쓰기 시험

기존 PaddleOCR 샘플 EPUB의 문단을 입력으로 사용한다. OCR 재실행은 하지 않는다.
kiwipiepy 0.23.2 및 kiwipiepy_model 0.23.0을 별도 Paddle 시험 환경에 설치했다.
공식 배포는 Windows/macOS를 지원하며 LGPLv3 라이선스다. 유지보수 상태와
플랫폼별 배포는 https://pypi.org/project/kiwipiepy/0.23.2/ 에서 확인했다.

`cleanup/spacing.py`는 Kiwi가 제안한 문장에서 공백 외 글자가 바뀌면 제안을 취소한다.
한글 음절 사이 ASCII 공백만 반영하여 영문·숫자·기호 주변 공백과 문단 경계는 유지한다.
따라서 문장부호 뒤 공백 누락은 이번 시험에서 교정하지 않는다.

```powershell
.\.tools\paddle-env\Scripts\python -m pip install kiwipiepy==0.23.2
.\.tools\paddle-env\Scripts\python scripts/trial_spacing.py
```

결과: `output/ivp-sample/ivp-pages-30-34-paddle-spacing.epub`.
`spacing-comparison.json`에 버전, 입력 해시, 문단별 전후 결과를 저장한다.
16문단 중 15문단의 공백이 변경됐고 공백 외 문자열 동일성, 원래 EPUB 해시 보존,
EPUBCheck 통과를 확인했다. 기존 Raw OCR과 Clean JSON에는 쓰지 않는다.

일반 문장은 개선됐지만 전문용어 '변증학'을 '변증 학'으로 나누거나 '산 전통'을
'산전 통'으로 처리하는 한계가 있다. OCR 오인식 자체는 고치지 않는다.
기본 변환에 자동 적용하지 않은 비교용 결과이며, 전문용어·문맥 회귀 사례와
정답 띄어쓰기 평가를 추가한 뒤 채택 여부를 결정해야 한다.
