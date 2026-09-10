from pathlib import Path
import subprocess
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_STORED


class EPUBValidationError(ValueError):
    pass


def validate_structure(path: Path) -> None:
    """Quick packaging checks; not a substitute for EPUBCheck conformance."""
    try:
        with ZipFile(path) as archive:
            first = archive.infolist()[0]
            if first.filename != "mimetype" or first.compress_type != ZIP_STORED:
                raise EPUBValidationError("EPUB mimetype must be first and uncompressed")
            if archive.read("mimetype") != b"application/epub+zip":
                raise EPUBValidationError("Invalid EPUB mimetype")
            if archive.testzip() is not None:
                raise EPUBValidationError("Corrupt EPUB member")
            for name in ("META-INF/container.xml", "EPUB/package.opf", "EPUB/nav.xhtml", "EPUB/chapter.xhtml"):
                ET.fromstring(archive.read(name))
    except EPUBValidationError:
        raise
    except Exception as exc:
        raise EPUBValidationError(f"Invalid EPUB structure: {exc}") from exc


def validate_epub(path: Path, jar: Path, java: str = "java") -> str:
    validate_structure(path)
    if not jar.is_file():
        raise EPUBValidationError(f"EPUBCheck JAR not found: {jar}")
    try:
        result = subprocess.run([java, "-jar", str(jar.resolve()), str(path.resolve())],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EPUBValidationError(f"Cannot run EPUBCheck: {exc}") from exc
    report = result.stdout + result.stderr
    if result.returncode != 0:
        raise EPUBValidationError(report)
    return report
