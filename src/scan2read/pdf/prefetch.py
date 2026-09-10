"""Prepare at most one page ahead in a separate, CPU-only process."""
from dataclasses import dataclass
import multiprocessing as mp
from multiprocessing.connection import wait
import os
from pathlib import Path
import threading

from scan2read.ocr.models import OCRPage
from scan2read.pdf.renderer import render_page
from scan2read.pdf.text_layer import extract_text_layer, find_corrupted_blocks


@dataclass(frozen=True)
class PreparedPage:
    number: int
    image: Path
    text_page: OCRPage | None


def prepare_page(source: Path, number: int, image: Path, dpi: int, use_text_layer: bool) -> PreparedPage:
    text_page = extract_text_layer(source, number, dpi) if use_text_layer else None
    if (text_page is None or find_corrupted_blocks(text_page)) and not image.exists():
        render_page(source, number, image, dpi)
    return PreparedPage(number, image, text_page)


def _worker(connection):
    # GUI cancellation terminates its CLI subprocess. Exit even if that parent
    # dies while this worker is rendering, rather than leaving an orphan.
    parent = mp.parent_process()
    if parent is not None:
        def watch_parent():
            wait([parent.sentinel])
            os._exit(0)
        threading.Thread(target=watch_parent, daemon=True).start()
    try:
        while True:
            request = connection.recv()
            if request is None:
                return
            try:
                connection.send((True, prepare_page(*request)))
            except Exception as exc:
                connection.send((False, f"Page {request[1]} preparation failed: {type(exc).__name__}: {exc}"))
    except (EOFError, BrokenPipeError, OSError):
        return
    finally:
        connection.close()


class PagePrefetch:
    """An ordered, bounded iterator; the caller must use it as a context manager."""
    def __init__(self, source: Path, numbers, image_dir: Path, dpi: int, use_text_layer: bool):
        self.source = source
        self.numbers = iter(numbers)
        self.image_dir = image_dir
        self.dpi = dpi
        self.use_text_layer = use_text_layer
        self.process = None
        self.connection = None
        self.pending = False

    def __enter__(self):
        return self

    def __iter__(self):
        return self

    def _submit(self):
        number = next(self.numbers, None)
        if number is None:
            self.pending = False
            return
        if self.process is None:
            context = mp.get_context("spawn")
            self.connection, child = context.Pipe()
            self.process = context.Process(target=_worker, args=(child,), daemon=True)
            try:
                self.process.start()
            except BaseException:
                self.connection.close()
                self.process = None
                raise
            finally:
                child.close()
        self.connection.send((self.source, number, self.image_dir / f"page_{number:04d}.png", self.dpi, self.use_text_layer))
        self.pending = True

    def __next__(self):
        if not self.pending:
            self._submit()
        if not self.pending:
            raise StopIteration
        try:
            while not self.connection.poll(.1):
                if not self.process.is_alive():
                    raise RuntimeError("Page preparation worker stopped unexpectedly")
            success, result = self.connection.recv()
        except (EOFError, BrokenPipeError, OSError) as exc:
            raise RuntimeError("Page preparation worker disconnected") from exc
        self.pending = False
        if not success:
            raise RuntimeError(result)
        self._submit()  # Next page renders while the caller recognizes this one.
        return result

    def __exit__(self, *_):
        if self.process is not None:
            # No OCR runs here; terminating only discards an uncommitted image.
            # The renderer publishes PNGs atomically and can retry its .tmp file.
            if self.process.is_alive() and not self.pending:
                try:
                    self.connection.send(None)
                    self.process.join(timeout=5)
                except (BrokenPipeError, EOFError, OSError):
                    pass
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(timeout=5)
            if self.process.is_alive():
                self.process.kill()
                self.process.join()
            self.process.close()
        if self.connection is not None:
            self.connection.close()
