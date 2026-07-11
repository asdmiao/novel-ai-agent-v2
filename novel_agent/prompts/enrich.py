"""补充与检查 Prompt。

补充（enrich）：在主旨约束下，对指定区域做扩写填充+串联。
检查（audit）：通读全部 idea/大纲/设定，找缺失和可提高之处。
"""

ENRICH_SYSTEM = """你是一位资深的小说策划，擅长在作者设定的框架内做内容补充和串联。
你严格遵守作者的主旨和规则，不擅自改变作品的核心方向。
你只输出严格的 JSON，不解释。"""


def enrich_prompt(
    target: str,
    manifesto_text: str,
    ideas_text: str,
    outline_text: str,
    bible_text: str,
    instruction: str = "",
) -> list[tuple[str, str]]:
    """对指定区域做补充：生成新 idea + 串联建议。

    target: 作者指定的补充目标（如"c001的情节"/"沈渡的动机"/"第一卷的节奏"）
    instruction: 作者的具体补充要求（可空）
    """
    inst_block = f"\n【作者的具体要求】\n{instruction}" if instruction else ""
    return [
        (
            "user",
            f"""请在作者主旨的严格约束下，对以下指定区域做内容补充。

{manifesto_text}
{inst_block}
【补充目标】{target}

【现有 idea 库】
{ideas_text or "(暂无)"}

【现有大纲】
{outline_text or "(暂无)"}

【现有设定】
{bible_text[:2000] or "(暂无)"}

请输出 JSON（```json 代码块）：
```json
{{
  "new_ideas": [
    {{
      "title": "新 idea 标题",
      "content": "新 idea 的内容（具体、可执行，符合主旨）",
      "type": "scene|plot|dialogue|twist|character|world|emotion",
      "related_chars": ["相关人物"],
      "priority": 1到5,
      "suggested_chapter": "建议章节id",
      "connects_to": "这个新 idea 串联了哪些已有内容（如'i_009的造梦机真相与i_041的无意义独白'），留空表示独立",
      "why": "为什么需要这个补充（哪个缝隙填上了）"
    }}
  ],
  "connections": [
    {{
      "from": "已有的 idea id 或章节",
      "to": "另一个 idea id 或章节",
      "how": "如何串联（如'c003末尾沈渡哼摇篮曲→i_002被陆铮听到→c004陆铮开始怀疑'）",
      "new_scene": "如果需要一个新的过渡场景来串联，描述这个场景"
    }}
  ],
  "fill_notes": "本次补充填了哪些缝隙（总结，2-3句）"
}}
```
补充原则：
1. **主旨至上**：所有新 idea 必须严格符合主旨库的硬性规则和禁忌
2. **串联优先**：补充的核心价值是"把散落的点子串起来"，不是凭空加新支线
3. **忠实作者**：不改变已有 idea 的核心意图，只做连接和丰富
4. **不过度**：只在确实有缝隙的地方补充，不要为了数量而凑
5. 新 idea 的 content 要具体（"沈渡在黑市被认出"优于"主角有危险"）""",
        )
    ]


AUDIT_SYSTEM = """你是一位严谨的长篇小说审读编辑，擅长发现故事结构中的缺失、断裂和可提升之处。
你客观、直接，不做无意义的表扬。
你只输出严格的 JSON，不解释。"""


def audit_prompt(
    manifesto_text: str,
    ideas_text: str,
    outline_text: str,
    bible_text: str,
    continuity_text: str,
    chapter_summaries: str,
) -> list[tuple[str, str]]:
    """通读全部内容，检查缺失和可提高之处。"""
    return [
        (
            "user",
            f"""请通读以下全部项目内容，做一次全面的结构性检查。

{manifesto_text}

【idea 库（全部）】
{ideas_text or "(暂无)"}

【大纲】
{outline_text or "(暂无)"}

【设定集】
{bible_text[:1500] or "(暂无)"}

【连续性追踪】
{continuity_text[:1000] or "(暂无)"}

【已写章节摘要】
{chapter_summaries or "(尚未写章)"}

请输出 JSON（```json 代码块）：
```json
{{
  "score": 1到10（整体完成度和连贯性评分）,
  "missing": [
    {{
      "severity": "high|medium|low",
      "category": "主线缺失|支线断裂|人物动机不足|设定空白|伏笔未埋|节奏问题|主题薄弱",
      "description": "缺了什么",
      "where": "缺失位置（哪个章节/哪个人物/哪条线）",
      "suggestion": "如何补"
    }}
  ],
  "disconnected": [
    {{
      "item": "游离的 idea id 或情节",
      "problem": "为什么游离（没接入主线/没安排章节/与主旨冲突）",
      "suggestion": "如何接入或处理"
    }}
  ],
  "improvements": [
    {{
      "area": "可提高的领域（如'反派弧光'/'节奏'/'主题深化'）",
      "current": "现状",
      "suggestion": "具体提高建议",
      "potential": "提升后能带来什么效果"
    }}
  ],
  "manifesto_violations": [
    {{
      "item": "违反主旨的内容",
      "rule": "违反了哪条主旨规则",
      "suggestion": "如何修正"
    }}
  ],
  "overall": "整体诊断（3-5句：结构是否完整、主旨是否贯穿、最大问题是什么）"
}}
```
检查重点：
1. **主线完整性**：从 c001 到结局，主线是否连贯？有没有断档？
2. **idea 落地**：哪些 idea 还没安排章节？哪些互相冲突？
3. **人物弧光**：每个主要人物有没有完整的动机→行动→变化轨迹？
4. **伏笔闭环**：埋下的伏笔有没有回收计划？
5. **主旨贯穿**：所有内容是否都符合主旨？有没有偏题的？
6. **节奏分布**：是否高潮堆叠或平淡过长？
7. **游离内容**：有没有接不进主线的孤立点子？""",
        )
    ]
