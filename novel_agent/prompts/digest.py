"""情节消化 Prompt：把自然语言情节描述忠实拆解成 idea。

设计原则（响应用户反馈）：
- 数量严格等于原文实际包含的点子数，1个就1个，10个就10个
- 忠实拆解，禁止自行衍生/扩展/发挥
- 仅在原文明确模糊处允许有限具体化
"""

DIGEST_SYSTEM = """你是一位严谨的小说策划助理。你的职责是把作者描述的情节，忠实地拆解成结构化条目。
你绝对不可以自行发挥、扩展、衍生作者没有写的内容。你只做"整理"，不做"创作"。
你只输出严格的 JSON，不解释。"""


def digest_plot_prompt(
    raw_text: str,
    project_meta: str,
    outline_text: str,
    existing_chars: list[str],
) -> list[tuple[str, str]]:
    """把一段自然语言情节描述，忠实拆解成 idea（不发挥、不扩展）。"""
    chars = "、".join(existing_chars) if existing_chars else "(从描述中识别)"
    return [
        (
            "user",
            f"""请把下面这段作者描述的【情节】，整理成结构化 idea 条目。

【当前项目】
{project_meta}

【现有大纲（参考用）】
{outline_text}

【已知人物】{chars}

【作者描述的情节】
{raw_text}

请输出 JSON（```json 代码块）：
```json
{{
  "ideas": [
    {{
      "title": "点子标题（10字内，直接概括原文这一点）",
      "content": "这一点子的内容（严格复述作者原意，1-2句）",
      "type": "scene|plot|dialogue|twist|character|world|emotion|other",
      "tags": ["标签（来自原文关键词）"],
      "related_chars": ["相关人物（来自原文）"],
      "priority": 1到5,
      "suggested_chapter": "建议章节id（能从大纲看出就填，看不出留空）",
      "from_original": "引用原文中对应的句子片段（证明这条来自原文，不是你编的）"
    }}
  ],
  "new_elements": [
    {{
      "kind": "character|location|faction|lore",
      "name": "原文中出现的新元素名",
      "summary": "根据原文的一句话描述",
      "original_quote": "原文中提到它的句子"
    }}
  ],
  "count_note": "实际拆出的 idea 数量说明（如'原文含3个独立点子'）"
}}
```

⚠️ 严格的拆解规则（必须遵守）：

1. **数量忠于原文**：原文里有几个独立点子就拆几条 idea。
   - 原文只有1个点子 → 只输出1条 idea
   - 原文有8个点子 → 输出8条 idea
   - 绝对不可以为了"凑数"而强行拆分或合并

2. **禁止自行扩展**：
   - 不可以给作者没写的情节、转折、人物、设定
   - 不可以"建议"作者应该加什么戏
   - 不可以基于你的想象补全剧情走向
   - 你只是"整理员"，不是"编剧"

3. **content 严格复述**：每条 idea 的 content 必须能在原文找到对应内容。
   - ✅ 原文"沈渡在走私船遇到老拾荒者警告他" → content: "沈渡在走私船遇老拾荒者，对方发出警告"
   - ❌ 自行扩展 → content: "沈渡在走私船遇到老拾荒者，对方警告回声灯塔是陷阱，并透露自己曾是灯塔守卫"（后两句是编的）

4. **唯一允许的"具体化"**：原文明确模糊时（如"某种武器""某个地方"），可以给出一个具体名字，但必须标注这是补充。除此之外不得发挥。

5. **from_original 字段必填**：每条 idea 必须引用原文片段，证明它来自作者而非你编造。如果某条 idea 找不到原文依据，就不要输出这条。

6. **new_elements 只记原文提到的**：原文出现的新人物/地点才记录，不要"建议"作者增加新人物。

7. **不输出 outline_beats**：大纲由作者手动维护，你不要给大纲建议。

8. **不输出 summary 评估**：不要评价作者的点子好坏，只整理。""",
        )
    ]
