"""作品主旨库（Manifesto）：存储作者对作品的核心思考。

这是整个知识库中【最高优先级】的约束层——所有生成内容（大纲/设定/正文/idea）
都必须严格遵守主旨库的规则。写作时作为第一段注入上下文。
"""

from __future__ import annotations

import time
from pathlib import Path

from pydantic import BaseModel, Field


class Manifesto(BaseModel):
    project: str = ""
    # 核心主旨：用一段话概括这部作品到底在讲什么、想表达什么
    core_theme: str = ""
    # 主线脉络：故事的核心推进逻辑（不是大纲，是底层逻辑）
    main_thread: str = ""
    # 情感基调：整本书的情感底色（如"虚无/冰冷/克制的温柔"）
    emotional_tone: str = ""
    # 哲学立场：作品的世界观/哲学倾向（如"虚无主义/存在主义/荒诞"）
    philosophy: str = ""
    # 硬性规则：作者明确的、绝对不可违反的创作准则
    # 例: ["不要英雄主义", "所有事物都无意义", "少女越单纯越好"]
    hard_rules: list[str] = Field(default_factory=list)
    # 风格指南：语言风格/叙事节奏/视角处理
    style_guide: str = ""
    # 禁忌清单：明确不能出现的东西
    # 例: ["不要热血逆袭", "不要主角光环", "不要说教"]
    taboos: list[str] = Field(default_factory=list)
    # 作者自由备注
    notes: str = ""
    updated_at: float = 0.0

    @classmethod
    def path_of(cls, project_dir: Path) -> Path:
        return project_dir / "manifesto.json"

    @classmethod
    def load(cls, project_dir: Path, project_name: str = "") -> "Manifesto":
        p = cls.path_of(project_dir)
        if not p.exists():
            return cls(project=project_name)
        with open(p, "r", encoding="utf-8") as f:
            return cls.model_validate_json(f.read())

    def save(self, project_dir: Path) -> None:
        self.updated_at = time.time()
        with open(self.path_of(project_dir), "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))

    def is_empty(self) -> bool:
        return not any(
            [
                self.core_theme,
                self.main_thread,
                self.emotional_tone,
                self.philosophy,
                self.hard_rules,
                self.style_guide,
                self.taboos,
                self.notes,
            ]
        )

    def render_for_prompt(self) -> str:
        """渲染为【最高优先级约束】，写作/补充/检查时必须第一个注入。"""
        if self.is_empty():
            return ""
        parts: list[str] = ["===== 📜 作品主旨（最高优先级，一切内容必须遵守）====="]
        if self.core_theme:
            parts.append(f"【核心主旨】{self.core_theme}")
        if self.main_thread:
            parts.append(f"【主线脉络】{self.main_thread}")
        if self.emotional_tone:
            parts.append(f"【情感基调】{self.emotional_tone}")
        if self.philosophy:
            parts.append(f"【哲学立场】{self.philosophy}")
        if self.hard_rules:
            parts.append("【硬性规则（绝对不可违反）】")
            for r in self.hard_rules:
                parts.append(f"  ⚠ {r}")
        if self.style_guide:
            parts.append(f"【风格指南】{self.style_guide}")
        if self.taboos:
            parts.append("【禁忌（绝对不能出现）】")
            for t in self.taboos:
                parts.append(f"  🚫 {t}")
        if self.notes:
            parts.append(f"【作者备注】{self.notes}")
        return "\n".join(parts)
