"""情节消化 Prompt：把自然语言情节描述拆解成结构化 idea + 大纲建议。"""

DIGEST_SYSTEM = """你是一位资深的小说策划编辑，擅长把作者随口描述的零散情节，拆解成结构化、可安插的创作素材。
你只输出严格的 JSON，不解释。"""


def digest_plot_prompt(
    raw_text: str,
    project_meta: str,
    outline_text: str,
    existing_chars: list[str],
) -> list[tuple[str, str]]:
    """把一段自然语言情节描述，拆解成多个 idea + 大纲/故事线建议。"""
    chars = "、".join(existing_chars) if existing_chars else "(从描述中识别)"
    return [
        (
            "user",
            f"""请把下面这段作者随口描述的【情节素材】，拆解成结构化的创作素材。

【当前项目】
{project_meta}

【现有大纲（用于判断安插位置）】
{outline_text}

【已知人物】{chars}

【作者描述的情节素材】
{raw_text}

请输出 JSON（```json 代码块）：
```json
{{
  "ideas": [
    {{
      "title": "这个点子的小标题（10字内）",
      "content": "点子的具体内容（1-2句，要具体可执行）",
      "type": "scene|plot|dialogue|twist|character|world|emotion|other",
      "tags": ["标签1", "标签2"],
      "related_chars": ["相关人物名（必须与已知人物匹配，或描述中新出现的）"],
      "priority": 1到5（5为最想用）,
      "suggested_chapter": "建议安插的章节id（如 c003，看不出来留空）",
      "reason": "为什么适合放这里（1句）"
    }}
  ],
  "outline_beats": [
    {{
      "chapter_id": "c00x",
      "beat_addition": "可作为该章新增/补充的情节节拍（具体描述这一章可以加什么戏）",
      "confidence": "high|medium|low"
    }}
  ],
  "new_elements": [
    {{
      "kind": "character|location|faction|lore",
      "name": "新元素名",
      "summary": "一句话简介",
      "why": "为什么需要这个新元素"
    }}
  ],
  "summary": "对作者这段素材的整体评估（2-3句：价值如何、如何融入主线）"
}}
```
拆解原则：
- ideas 要拆得细：一段描述里往往含多个独立点子，分别成条，不要合并
- 每个 idea 的 content 要具体（"沈渡在黑市被认出"优于"主角有危险"）
- related_chars 尽量关联到已知人物，新人物才放进 new_elements
- outline_beats 只在能自然融入现有章节时才给，牵强的不给
- priority 根据对主线的推动价值打分
- 如果素材里提到了新人物/新地点/新设定，放进 new_elements""",
        )
    ]
