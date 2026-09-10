# 구현 현황과 기술 선택

## 단계별 진행

- 완료: Python 3.12 src 프로젝트, 설치 가능한 CLI 진입점.
- 완료: PDF 존재 여부·페이지 수·메타데이터·첫 페이지 렌더링 검사.
- 완료: 페이지 단위 PNG 렌더링(기본 300 DPI), 자원 해제, 임시 파일 후 교체.
- 완료: OCR 인터페이스, 내부 데이터 모델, Tesseract TSV 어댑터, 덮어쓰기 없는 원본 JSON 저장.
- 완료: 위치 기반 숫자형 페이지 번호 제거, 줄 연결과 기본 문단 경계 처리.
- 완료: 캐시·재개, EPUB3 생성 및 EPUBCheck 검증, 전체 변환 CLI.

현재 CLI는 `convert`와 도움말·버전을 제공한다. 기본 구현 범위는 README의 실행 안내를 참고한다.

## 의존성

2026-09-07 공식 배포 정보를 확인하고 PDF 처리에는 pypdfium2 5.x,
PNG 저장에는 Pillow 12.x를 선택했다. 두 패키지는 Windows와 macOS용
배포를 제공한다. 현재 Windows Python 3.12에서 설치 및 렌더링을 검증했다.
macOS 실행 검증은 아직 하지 않았다.

- pypdfium2: Apache-2.0 또는 BSD-3-Clause. 포함된 PDFium과 서드파티 고지는 배포 시 보존해야 한다.
  https://pypi.org/project/pypdfium2/
- Pillow: MIT-CMU. https://pypi.org/project/Pillow/

권장 스택의 PyMuPDF 대신 교체 가능한 PDF 모듈 내부에 pypdfium2를 사용한다.
CLI와 테스트는 표준 라이브러리 argparse, unittest를 사용한다.
OCR 어댑터는 Tesseract를 로컬 subprocess로 실행한다. 기본 언어는 kor+eng이다.
Apache-2.0 라이선스, Windows/macOS 지원 및 유지되는 공식 문서를 확인했다.
별도 Python OCR 래퍼나 대형 학습 프레임워크 없이 위치·신뢰도 정보를 얻을 수 있어 선택했다.
공식 설치 안내: https://tesseract-ocr.github.io/tessdoc/Installation.html
플랫폼 안내: https://tesseract-ocr.github.io/tessdoc/supported-operating-systems.html
현재 PC의 기본 설치 경로에서 Tesseract와 kor/eng 데이터를 확인했고 실제 OCR 통합 테스트를 통과했다.
기본 PSM 6을 사용한다. TSV와 TXT를 한 번의 OCR 실행으로 생성하고 모든 줄의 공백 외 글자가 일치할 때만 TXT의 띄어쓰기를 내부 모델에 보존한다.

원본 JSON은 같은 경로에 재저장할 수 없다. 완성된 임시 파일을 hard link로
게시하므로 기존 파일을 덮어쓰지 않으며, 같은 파일시스템의 hard link 지원이 필요하다.
강제 OCR 재실행은 새 세대 디렉터리를 사용하여 기존 원본을 보존한다.

## 개발 실행

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python -m scan2read --help
.\.venv\Scripts\python -m unittest discover -s tests -v
```

원본 OCR, 정리 텍스트, TTS 텍스트는 별도 단계로 유지한다.
현재 테스트는 합성 PDF만 사용하며 외부로 문서를 전송하지 않는다.


## 현재 저장 구조

`work/<설정 SHA256>/project.json`에 원본 경로·페이지 수·DPI·상태·세대를 기록한다.
렌더링 결과는 `pages/`, 각 OCR 실행 세대는 `generations/<세대>/raw_ocr/`와
`generations/<세대>/clean/`에 저장한다. TTS 전용 변환은 아직 추가하지 않았다.
OCR 캐시 키에는 원본 PDF 해시, DPI, 실행 파일·언어 모델 해시와 PSM을 포함한다.

## EPUB 구현과 검증

단일 XHTML 본문과 EPUB3 navigation/package/container를 Python 표준 라이브러리로
생성한다. 최소 출력이므로 EbookLib를 추가하지 않았다. 본문은 페이지별로 처리하고
ZIP 멤버에 순차 기록한다. HTML/XML 특수문자는 이스케이프한다.
기본 메타데이터는 title, ko 언어, UUID, 수정 시각이다.
표지·저자·ISBN 옵션은 아직 구현하지 않았다.

빠른 ZIP/XML 검사 후 로컬 EPUBCheck를 필수 실행한다. 성공한 경우만 최종 경로로
교체한다. EPUBCheck 5.3.0은 W3C/DAISY가 관리하는 BSD-3-Clause Java 도구이며
Windows/macOS의 Java 환경에서 실행 가능하다.
https://github.com/w3c/epubcheck

2026-09-07 Windows 검증: 한국어 합성 스캔 2페이지 변환, 본문 정확 일치,
페이지 번호 제거, EPUBCheck 오류·경고 0건, 재실행 OCR 캐시 확인.
자동 테스트 21개(실제 OCR 및 EPUBCheck 통합 포함) 통과.
모바일 리더와 장시간 TTS 청취 및 macOS 실행은 아직 검증하지 않았다.
