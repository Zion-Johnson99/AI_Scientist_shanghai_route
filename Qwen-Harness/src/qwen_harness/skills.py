"""SkillRegistry: discovery and snapshot of .qoder/skills (design doc section 8).

The harness scans ONLY ``<repo>/.qoder/skills``. ``.agents/skills`` is never
touched. Each skill directory must contain a ``SKILL.md`` with YAML front
matter whose ``name`` matches the directory name.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml
from pydantic import Field

from .errors import SkillError
from .logging_utils import get_logger
from .models import StrictModel
from .run_store import RunStore

LOGGER = get_logger("skills")

#: The six project skills plus the existing route-optimization skill.
CORE_SKILLS: tuple[str, ...] = (
    "qwen-harness-orchestration",
    "scientific-evidence-hypothesis",
    "xuhui-route-builder-engineering",
    "weather-environment-pipeline",
    "evaluation-qwen-experiments",
    "web-product-integration",
)

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_CODE_REF_RE = re.compile(r"`([^`\s|<>]+\.(?:md|json|jsonl|py|csv|txt|ya?ml|geojson|ps1|sh|mjs))`")


class SkillDocument(StrictModel):
    name: str
    description: str
    root: Path
    skill_path: Path
    body: str
    referenced_files: list[Path] = Field(default_factory=list)
    sha256: str


def _split_front_matter(text: str) -> tuple[str | None, str]:
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None, text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "".join(lines[1:index]), "".join(lines[index + 1 :])
    return None, text


def _extract_reference_candidates(body: str) -> list[str]:
    candidates = _LINK_RE.findall(body) + _CODE_REF_RE.findall(body)
    cleaned: list[str] = []
    for item in candidates:
        item = item.strip()
        if not item or item.startswith(("http://", "https://", "mailto:", "#", "<")):
            continue
        cleaned.append(item.split("#", 1)[0])
    return cleaned


class SkillRegistry:
    def __init__(self, repository_root: Path) -> None:
        self.repository_root = Path(repository_root).resolve()
        self.skills_root = self.repository_root / ".qoder" / "skills"
        self._documents: dict[str, SkillDocument] | None = None

    # -- discovery --------------------------------------------------------------
    def discover(self) -> dict[str, SkillDocument]:
        if self._documents is not None:
            return self._documents
        documents: dict[str, SkillDocument] = {}
        if not self.skills_root.is_dir():
            raise SkillError(
                f"技能根目录不存在: {self.skills_root}",
                suggested_action="在仓库根目录创建 .qoder/skills 并放置六个项目技能",
            )
        for entry in sorted(self.skills_root.iterdir()):
            if not entry.is_dir():
                continue
            skill_path = entry / "SKILL.md"
            if not skill_path.is_file():
                LOGGER.debug("跳过缺少 SKILL.md 的目录: %s", entry)
                continue
            document = self._parse_skill(entry, skill_path)
            if document.name in documents:
                raise SkillError(f"技能名称重复: {document.name}")
            documents[document.name] = document
        self._documents = documents
        return documents

    def _parse_skill(self, skill_dir: Path, skill_path: Path) -> SkillDocument:
        try:
            raw = skill_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SkillError(f"无法读取 {skill_path}: {exc}") from exc
        front_matter, body = _split_front_matter(raw)
        if front_matter is None:
            raise SkillError(
                f"{skill_path} 缺少 YAML front matter",
                suggested_action="SKILL.md 首部必须是 --- 包裹的 name/description 声明",
            )
        try:
            meta = yaml.safe_load(front_matter)
        except yaml.YAMLError as exc:
            raise SkillError(f"{skill_path} front matter 不是合法 YAML: {exc}") from exc
        if not isinstance(meta, dict):
            raise SkillError(f"{skill_path} front matter 必须是键值映射")
        name = str(meta.get("name", "")).strip()
        description = str(meta.get("description", "")).strip()
        if not name:
            raise SkillError(f"{skill_path} front matter 缺少 name 字段")
        if name != skill_dir.name:
            raise SkillError(
                f"技能 name={name!r} 与目录名 {skill_dir.name!r} 不一致",
                suggested_action="重命名目录或修正 front matter 的 name",
            )
        if not description:
            raise SkillError(f"{skill_path} front matter 缺少 description 字段")

        referenced: list[Path] = []
        seen: set[Path] = set()
        for candidate in _extract_reference_candidates(body):
            try:
                resolved = (skill_dir / candidate).resolve()
                resolved.relative_to(skill_dir.resolve())
            except (ValueError, OSError):
                LOGGER.debug("引用文件越界已忽略: %s -> %s", skill_dir.name, candidate)
                continue
            if resolved.is_file() and resolved not in seen and resolved != skill_path:
                seen.add(resolved)
                referenced.append(resolved)
        referenced.sort()

        digest = hashlib.sha256(skill_path.read_bytes())
        for ref in referenced:
            digest.update(ref.relative_to(skill_dir).as_posix().encode("utf-8"))
            digest.update(ref.read_bytes())
        return SkillDocument(
            name=name,
            description=description,
            root=skill_dir.resolve(),
            skill_path=skill_path.resolve(),
            body=body,
            referenced_files=referenced,
            sha256=digest.hexdigest(),
        )

    # -- access --------------------------------------------------------------
    def require(self, names: list[str]) -> list[SkillDocument]:
        documents = self.discover()
        missing = sorted(set(names) - set(documents))
        if missing:
            raise SkillError(
                f"缺少必需技能: {', '.join(missing)}",
                suggested_action="运行 `qwen-harness doctor` 检查 .qoder/skills 内容",
            )
        return [documents[name] for name in names]

    def load_reference(self, skill_name: str, relative_path: str) -> str:
        documents = self.discover()
        if skill_name not in documents:
            raise SkillError(f"技能不存在: {skill_name}")
        skill_dir = documents[skill_name].root
        resolved = (skill_dir / relative_path).resolve()
        try:
            resolved.relative_to(skill_dir)
        except ValueError as exc:
            raise SkillError(
                f"引用文件越界: {relative_path} 不在技能 {skill_name} 目录内",
            ) from exc
        if not resolved.is_file():
            raise SkillError(f"引用文件不存在: {resolved}")
        return resolved.read_text(encoding="utf-8")

    def snapshot(self, run_store: RunStore, names: list[str]) -> list[Path]:
        """Copy SKILL.md and referenced files into the run's skills/ dir."""
        documents = self.discover()
        written: list[Path] = []
        for name in names:
            document = documents.get(name)
            if document is None:
                LOGGER.warning("快照时技能缺失，已跳过: %s", name)
                continue
            target_rel = f"skills/{name}/SKILL.md"
            written.append(run_store.write_bytes_atomic(target_rel, document.skill_path.read_bytes()))
            for ref in document.referenced_files:
                rel = ref.relative_to(document.root).as_posix()
                written.append(run_store.write_bytes_atomic(f"skills/{name}/{rel}", ref.read_bytes()))
        return written
