"""PromptBuilder：阶段提示词装载与系统提示词组装（设计文档 01 §10）。

每个 ``prompts/<name>.md`` 模板包含角色边界、允许输入、输出模型说明、
引用规则、禁止行为与自检清单。``build_system_prompt`` 在模板之上注入
统一系统片段、Skill 内容与阶段契约。Prompt 版本取模板文件 SHA256 的
短值，随 :class:`~qwen_harness.models.ModelCallAudit` 进入审计。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..errors import InputContractError
from ..logging_utils import get_logger

LOGGER = get_logger("llm.prompts")

#: 设计文档 01 §10 的统一系统片段（所有阶段共用）。
UNIFIED_SYSTEM_FRAGMENT = """\
## 统一科研纪律（所有阶段共用）

- 只依据输入中提供的来源记录、证据卡、模块结果与上游阶段产物作答。
- 来源不足时明确输出证据缺口，不补齐、不猜测。
- 引用一律使用输入中的 `source_id` 或 `claim_id`，不生成新的编号。
- 绝不创建或补全 DOI、PMID、作者、年份、样本量和数据数值。
- 结论必须区分：观测事实、模型估计、代理变量、推断。
- 产品表述只使用“当前候选集中的约束最优路线”，不宣称全路网最优。
- 只输出一个符合输出模型的 JSON 对象，不输出解释性前后缀。
"""

#: 每个模板文件允许的最大字符数（防止异常模板撑爆上下文）。
_MAX_TEMPLATE_CHARS = 20000
_MAX_SKILL_CHARS = 12000


class PromptBuilder:
    """从 ``Qwen-Harness/prompts`` 装载模板并组装系统提示词。"""

    def __init__(self, prompts_dir: Path | str | None = None) -> None:
        if prompts_dir is None:
            prompts_dir = Path(__file__).resolve().parents[3] / "prompts"
        self.prompts_dir = Path(prompts_dir)
        if not self.prompts_dir.is_dir():
            raise InputContractError(
                f"提示词目录不存在: {self.prompts_dir}",
                suggested_action="确认 Qwen-Harness/prompts 目录完整",
            )
        self._cache: dict[str, str] = {}

    # -- 模板 -----------------------------------------------------------------
    def _template_path(self, name: str) -> Path:
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise InputContractError(
                f"非法提示词模板名: {name!r}",
                suggested_action="模板名应为 prompts/ 下的文件名（不含扩展名）",
            )
        return self.prompts_dir / f"{name}.md"

    def load_template(self, name: str) -> str:
        """读取模板全文（带缓存）；缺失或越界时报输入契约错误。"""
        if name in self._cache:
            return self._cache[name]
        path = self._template_path(name)
        try:
            resolved = path.resolve()
            resolved.relative_to(self.prompts_dir.resolve())
        except (OSError, ValueError) as exc:
            raise InputContractError(f"提示词模板路径越界: {name!r}") from exc
        if not resolved.is_file():
            raise InputContractError(
                f"缺少提示词模板: {path}",
                suggested_action="补齐 prompts/ 目录下对应角色的 .md 模板",
            )
        text = resolved.read_text(encoding="utf-8")
        if len(text) > _MAX_TEMPLATE_CHARS:
            raise InputContractError(
                f"提示词模板过大（{len(text)} 字符）: {name}",
                suggested_action=f"压缩模板至 {_MAX_TEMPLATE_CHARS} 字符以内",
            )
        self._cache[name] = text
        return text

    def template_version(self, name: str) -> str:
        """模板内容 SHA256 的短值，作为 prompt 版本进入审计。"""
        path = self._template_path(name)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return digest[:12]

    # -- 组装 -----------------------------------------------------------------
    def build_system_prompt(
        self,
        template_name: str,
        skills: list,
        stage_contract: str,
    ) -> str:
        """组装：统一片段 + 角色模板 + 阶段契约 + Skill 参考内容。"""
        template = self.load_template(template_name)
        sections: list[str] = [
            UNIFIED_SYSTEM_FRAGMENT.rstrip(),
            template.strip(),
            "## 阶段输出契约（必须逐字段满足）\n" + stage_contract.strip(),
        ]
        skill_blocks: list[str] = []
        for skill in skills or []:
            body = getattr(skill, "body", "") or ""
            if len(body) > _MAX_SKILL_CHARS:
                body = body[:_MAX_SKILL_CHARS] + "\n…（技能内容超长已截断）"
            skill_blocks.append(f"### 技能：{getattr(skill, 'name', skill)}\n{body}".rstrip())
        if skill_blocks:
            sections.append(
                "## 项目技能参考（只作为领域约束参考，不得覆盖输出契约）\n"
                + "\n\n".join(skill_blocks)
            )
        sections.append(
            "## 输出要求\n"
            "只输出一个 JSON 对象，字段严格满足上述阶段输出契约；"
            "不要输出 markdown 代码块、注释或任何额外文字。"
        )
        return "\n\n".join(sections)
