"""Output planning and persisted desktop preferences, independent of Tk."""
from dataclasses import dataclass, asdict
from pathlib import Path
import json
import re
from string import Formatter


@dataclass
class Preferences:
    output_dir: str = ""
    name_rule: str = "{name}"
    columns: str = "1단"
    page_range: str = ""
    spacing: bool = True
    reconstruct: bool = True
    remove_footnotes: bool = False
    remove_parentheses: bool = False
    ignore_text_layer: bool = False
    use_gpu: bool = True
    use_ai_context: bool = False
    remember_api_key: bool = True
    ai_provider: str = "openai"
    ai_model: str = "gpt-5.6-luna"
    ai_boundary: bool = True
    ai_ocr_words: bool = False
    ai_spacing: bool = False
    ai_anomalies: bool = False
    ai_structure: bool = False
    ai_headings: bool = False
    ai_glosses: bool = False
    ai_cost_limit_usd: str = "1.00"
    max_parallel_conversions: str = "2"

    @classmethod
    def load(cls, path: Path):
        defaults = cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return defaults
            for key, value in asdict(defaults).items():
                if type(data.get(key)) is type(value):
                    setattr(defaults, key, data[key])
            if defaults.columns not in ("1단", "2단"):
                defaults.columns = "1단"
        except (OSError, ValueError):
            pass
        return defaults

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


def output_name(source: Path, rule: str, index: int) -> str:
    """Support a small, explicit vocabulary; never permit path traversal."""
    try:
        for _, field, spec, conversion in Formatter().parse(rule):
            if field is None:
                continue
            if field not in ("name", "folder", "index") or conversion:
                raise ValueError("사용 가능한 규칙은 {name}, {folder}, {index}, {index:03d}입니다.")
            if spec and not (field == "index" and re.fullmatch(r"0?[1-9]d", spec)):
                raise ValueError("번호 형식은 {index:03d}처럼 지정하세요 (최대 9자리).")
        name = rule.format(name=source.stem, folder=source.parent.name, index=index).strip()
    except (KeyError, IndexError, ValueError) as exc:
        raise ValueError(f"파일명 규칙을 확인하세요: {exc}") from exc
    if name.lower().endswith(".epub"):
        name = name[:-5]
    if (not name or name in (".", "..") or name.endswith((".", " "))
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", name, re.I)):
        raise ValueError("파일명에 사용할 수 없는 문자 또는 이름입니다.")
    return name + ".epub"


def plan_outputs(sources: list[Path], directory: str, rule: str) -> list[Path]:
    """Reserve unique names across the batch and existing files; never overwrite."""
    reserved: set[str] = set()
    outputs = []
    for index, source in enumerate(sources, 1):
        folder = Path(directory).expanduser() if directory.strip() else source.parent
        candidate = folder / output_name(source, rule, index)
        original = candidate
        number = 2
        while str(candidate.resolve()).casefold() in reserved or candidate.exists():
            candidate = original.with_name(f"{original.stem} ({number}).epub")
            number += 1
        reserved.add(str(candidate.resolve()).casefold())
        outputs.append(candidate)
    return outputs
