"""Run the local IVP comparison in the isolated Paddle environment."""
import logging
from pathlib import Path
import time
import json
from importlib.metadata import version
from scan2read.ocr.paddle import PaddleEngine
from scan2read.ocr.columns import TwoColumnEngine
from scan2read.pipeline import convert
from scan2read.epub.validator import validate_epub

logging.basicConfig(level=logging.INFO)
root = Path("output/ivp-sample")
started = time.monotonic()
engine = TwoColumnEngine(PaddleEngine())
identity = f"paddle-trial-v1:det=PP-OCRv5_mobile_det:rec=korean_PP-OCRv5_mobile_rec:columns-v2:{version('paddleocr')}:{version('paddlepaddle')}"
convert(root / "ivp-pdf-pages-30-34.pdf", root / "ivp-pages-30-34-paddle.epub",
        Path("work/ivp-paddle"), engine, identity,
        lambda path: validate_epub(path, Path(".tools/epubcheck-5.3.0/epubcheck.jar")))
(root / "paddle-run.json").write_text(json.dumps({"seconds_including_model_loading": time.monotonic()-started,
                                               "engine": identity}, indent=2), encoding="utf-8")
