"""Optional local PaddleOCR adapter; no import cost for Tesseract users."""
from pathlib import Path
import hashlib
import json
import os
from importlib.metadata import PackageNotFoundError, version
from PIL import Image
from scan2read.ocr.models import OCRBlock, OCRPage


# PaddleOCR recognizes one detected text line per model call by default,
# which under-uses a GPU (many tiny kernel launches with idle time between).
# Batching multiple line crops into one call measurably raises throughput
# (~30% faster on a typical page) and GPU utilization; the recognized text
# can shift by a character in rare cases due to batched-inference floating
# point differences, so this is part of cache_identity like device is.
RECOGNITION_BATCH_SIZE = 16


def _paddle_version() -> str:
    """The installed paddle version, from whichever of the two distributions provides it."""
    try:
        return version("paddlepaddle")
    except PackageNotFoundError:
        return version("paddlepaddle-gpu")


def convert_result(result, width: int, height: int) -> OCRPage:
    rows = []
    for text, score, polygon in zip(result["rec_texts"], result["rec_scores"], result["rec_polys"], strict=True):
        xs = [float(point[0]) for point in polygon]
        ys = [float(point[1]) for point in polygon]
        box = (max(0, int(min(xs))), max(0, int(min(ys))),
               min(width, int(max(xs))), min(height, int(max(ys))))
        rows.append((box, text, float(score)))
    # The wrapper supplies one column; retain top-to-bottom order inside it.
    rows.sort(key=lambda row: (row[0][1], row[0][0]))
    return OCRPage(1, width, height, tuple(OCRBlock(str(i), text, box, score, i)
                                        for i, (box, text, score) in enumerate(rows)))


class PaddleEngine:
    def __init__(self, device: str = "cpu"):
        from paddleocr import PaddleOCR
        self.device = device
        self.model_root = Path(os.environ.get("SCAN2READ_MODELS", str(Path.home()/".paddlex"/"official_models")))
        self.names = ("PP-OCRv5_mobile_det", "korean_PP-OCRv5_mobile_rec")
        model_paths = {}
        if all((self.model_root/name).is_dir() for name in self.names):
            model_paths = {"text_detection_model_dir": str(self.model_root/self.names[0]),
                           "text_recognition_model_dir": str(self.model_root/self.names[1])}
        self.model = PaddleOCR(
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
            use_doc_orientation_classify=False, use_doc_unwarping=False,
            use_textline_orientation=False, device=device, enable_mkldnn=False,
            text_recognition_batch_size=RECOGNITION_BATCH_SIZE, **model_paths,
        )

    def cache_identity(self) -> str:
        hashes = {}
        for name in self.names:
            for filename in ("inference.json", "inference.pdiparams", "inference.yml"):
                path = self.model_root/name/filename
                with path.open("rb") as stream:
                    hashes[f"{name}/{filename}"] = hashlib.file_digest(stream,"sha256").hexdigest()
        return json.dumps({"adapter":1,"paddleocr":version("paddleocr"),
                           "paddlepaddle":_paddle_version(),"device":self.device,
                           "recognition_batch_size":RECOGNITION_BATCH_SIZE,"models":hashes},sort_keys=True)

    def recognize(self, image_path: Path) -> OCRPage:
        results = list(self.model.predict(str(image_path.resolve())))
        if len(results) != 1:
            raise ValueError("Expected one PaddleOCR page result")
        with Image.open(image_path) as image:
            return convert_result(results[0], *image.size)
