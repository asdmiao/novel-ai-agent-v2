"""记忆系统：为长篇小说提供"上下文压缩"。

核心思路：
  - 写第 N 章时，不可能把 1..N-1 章全文塞进去（上下文爆炸）
  - 改为：全书设定集 + 大纲 + 最近 K 章的【摘要】+ 第 N-1 章末尾若干字
  - 这样既保持连贯，又控制 token 数
"""

from __future__ import annotations

from pathlib import Path

from .bible import Bible
from .chapter import ChapterStore
from .continuity import Continuity
from .ideas import IdeaBank
from .manifesto import Manifesto
from .outline import Outline, ChapterStatus
from .threads import ThreadNetwork
from .world import World
from .search import SearchEngine
from ..llm.embedding import build_embedding
from .idea_retrieval import IdeaRetriever
from .constraints import adapt_continuity, ActiveConstraintResolver
from .conflicts import detect_conflicts, load_conflicts, load_confirmations, load_governance_state
from .links import IdeaLinkResolver
from .chapter_fit import ChapterFitResolver
from dataclasses import dataclass, field


@dataclass
class ContextBundle:
    text: str
    deterministic_sources: list[dict] = field(default_factory=list)
    selected_ideas: list[dict] = field(default_factory=list)
    retrieved_sources: list[dict] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    threads: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    confirmations: list[dict] = field(default_factory=list)


class Memory:
    """把项目里散落的"记忆"打包成一份给 LLM 的上下文。"""

    def __init__(
        self,
        project_dir: Path,
        outline: Outline,
        bible: Bible,
        store: ChapterStore,
        continuity: Continuity | None = None,
        *,
        world: World | None = None,
        ideas: IdeaBank | None = None,
        threads: ThreadNetwork | None = None,
        manifesto: Manifesto | None = None,
        embedding_config: dict | None = None,
        rag_top_k: int = 6,
        rag_max_chars: int = 5000,
        recent_summary_count: int = 3,
        recent_text_chars: int = 600,
    ) -> None:
        self.project_dir = project_dir
        self.outline = outline
        self.bible = bible
        self.store = store
        self.continuity = continuity or Continuity()
        self.world = world or World()
        self.ideas = ideas or IdeaBank()
        self.threads = threads or ThreadNetwork()
        self.manifesto = manifesto or Manifesto()
        self.embedding_config = embedding_config or {}
        self.rag_top_k = rag_top_k
        self.rag_max_chars = rag_max_chars
        self.recent_summary_count = recent_summary_count
        self.recent_text_chars = recent_text_chars

    def build_context_for_chapter(self, chapter_id: str) -> str:
        return self.build_context_bundle(chapter_id).text

    def build_context_bundle(self, chapter_id: str) -> ContextBundle:
        """为"写第 chapter_id 章"组装上下文。

        包含：
          1. 全书设定集（人物/地点/势力/物品/设定）
          2. 大纲（已写章节 + 当前章节计划 + 后续 1-2 章）
          3. 最近 K 章的摘要
          4. 上一章末尾原文（衔接）
          5. 当前章节详细计划
        """
        plan = self.outline.find(chapter_id)
        if plan is None:
            raise ValueError(f"大纲里找不到章节 {chapter_id}")

        all_ch = self.outline.all_chapters()
        try:
            idx = all_ch.index(plan)
        except ValueError:
            idx = 0

        # 1. 设定集（优先本章涉及的人物/地点）
        related: set[str] = set()
        for name in (
            (plan.characters or [])
            + ([plan.pov] if plan.pov else [])
            + ([plan.setting] if plan.setting else [])
        ):
            for c in self.bible.characters:
                if name and (name in c.name or c.name in name):
                    related.add(c.id)
            for l in self.bible.locations:
                if name and (name in l.name or l.name in name):
                    related.add(l.id)
        bible_text = self.bible.render_for_prompt(related if related else None)

        # 2. 大纲（只显示"已写 + 当前 + 后 1"）
        upcoming = all_ch[: idx + 2]
        outline_text = self.outline.render_for_prompt()
        # 简化：直接全量大纲也可以，但太长时截断
        if len(outline_text) > 2500:
            outline_text = self._compact_outline(upcoming)

        # 3. 最近 K 章摘要
        done_ids = [c.chapter_id for c in all_ch[:idx] if self.store.has(c.chapter_id)]
        recent = (
            done_ids[-self.recent_summary_count :] if self.recent_summary_count else []
        )
        summaries_block = self._format_summaries(recent)

        # 4. 上一章末尾原文
        prev_text = ""
        if done_ids:
            prev_text = self.store.tail(
                self.project_dir, done_ids[-1], self.recent_text_chars
            )

        # 5. 当前章节计划
        current = plan.render_for_prompt()

        # RAG: 用当前章节的剧情要素召回历史片段、设定和连续性资料。
        rag_query = " ".join(
            x for x in [plan.title, plan.beat, plan.goal, plan.conflict, plan.ending]
            if x
        )
        rag_text = ""
        retrieved_sources: list[dict] = []
        if rag_query:
            engine = SearchEngine(self.project_dir)
            embedder = None
            if self.embedding_config:
                try:
                    embedder = build_embedding(self.embedding_config)
                except Exception:  # noqa: BLE001
                    embedder = None
            # 首次使用时自动建立向量索引；已有索引则直接复用。
            engine.ensure_index_fresh(bible=self.bible, continuity=self.continuity,
                world=self.world, ideas=self.ideas, store=self.store,
                project_dir=self.project_dir, embedder=embedder)
            # 查询改写：去掉常见叙事虚词，保留实体与剧情谓词，提高召回精度。
            stopwords = {"本章", "这一章", "需要", "进行", "发生", "以及", "相关"}
            retrieval_query = " ".join(
                token for token in rag_query.split() if token not in stopwords
            ) or rag_query
            hits = engine.hybrid_search(
                retrieval_query, embedder=embedder,
                kinds=["chapter_chunk", "summary", "character", "location",
                       "faction", "item", "lore", "world", "foreshadow",
                       "fact", "promise"],
                top_k=self.rag_top_k,
            )
            seen: set[str] = set()
            lines: list[str] = []
            used = 0
            for hit in hits:
                key = f"{hit.doc.ref}:{hit.doc.text[:80]}"
                if key in seen:
                    continue
                source = hit.doc.ref
                block = f"【来源:{source} | {hit.doc.title or hit.doc.kind} | 相关度:{hit.score:.2f}】{hit.doc.text}"
                if used + len(block) > self.rag_max_chars:
                    break
                seen.add(key)
                lines.append(block)
                retrieved_sources.append({"source_id": hit.doc.id, "source_type": hit.doc.kind,
                    "source_ref": hit.doc.ref, "score": hit.score, "retrieval_method": "hybrid"})
                used += len(block)
            rag_text = "\n".join(lines)

        # 连续性约束（伏笔/持有物/承诺/既定事实）——防止长篇崩坏的关键
        continuity_views = adapt_continuity(self.continuity, self.bible, self.world)
        governance = load_governance_state(self.project_dir)
        for c in continuity_views:
            saved = governance.get("constraints", {}).get(c.id, {})
            if saved:
                c.status = saved.get("status", c.status)
                c.supersedes = list(saved.get("supersedes", c.supersedes))
        active_views = ActiveConstraintResolver().resolve(continuity_views, chapter_id)
        persisted_conflicts = load_conflicts(self.project_dir)
        conflict_reports = persisted_conflicts or detect_conflicts(active_views)
        confirmations = load_confirmations(self.project_dir)
        continuity_text = self.continuity.render_for_prompt()

        # 世界观硬约束（绝对不能违反）
        world_constraints = self.world.render_for_prompt(with_constraints_only=True)

        # 故事线脉络（让 LLM 知道当前在哪条线的哪个节点）
        threads_text = self.threads.render_for_prompt(only_active=True)

        # Idea 多通道召回与重排（保留原规则信号）
        ideas_text = ""
        available = self.ideas.available()
        selected_ideas = []
        link_resolver = IdeaLinkResolver(self.ideas, self.threads)
        if available:
            engine = SearchEngine(self.project_dir)
            embedder_for_ideas = None
            if self.embedding_config:
                try: embedder_for_ideas = build_embedding(self.embedding_config)
                except Exception: pass
            engine.ensure_index_fresh(bible=self.bible, continuity=self.continuity, world=self.world, ideas=self.ideas, store=self.store, project_dir=self.project_dir, embedder=embedder_for_ideas)
            results = IdeaRetriever().retrieve(plan=plan, ideas=self.ideas, threads=self.threads, search_engine=engine, embedder=embedder_for_ideas, project_dir=self.project_dir, top_k=8)
            pool = [r.idea for r in results]
            ideas_text = self.ideas.render_for_prompt(pool)
            selected_ideas = []
            for r in results:
                link = link_resolver.resolve(r.idea.id)
                fit = ChapterFitResolver().resolve(r.idea, chapter_id, self.threads, link)
                if fit.decision == "deferred":
                    continue
                selected_ideas.append({"source_id": r.source_id, "source_type": "idea", "source_ref": r.idea.id, "selection_reason": "+".join(r.retrieval_channels), "retrieval_channels": r.retrieval_channels, "score": r.final_score, "status": r.status, "reasons": r.reasons + fit.reasons, "thread_ids": link.thread_ids, "planned_chapters": link.planned_chapters, "used_chapters": link.used_chapters, "chapter_fit": fit.chapter_fit, "decision": fit.decision, "selected": True, "used": "unknown"})

        parts: list[str] = []

        # 📜 主旨——最高优先级，放在第一段
        manifesto_text = self.manifesto.render_for_prompt()
        if manifesto_text:
            parts.append(manifesto_text)

        parts.append("===== 故事设定 =====")
        parts.append(bible_text)
        if world_constraints:
            parts.append("===== 世界观硬约束（绝对不能违反）=====")
            parts.append(world_constraints)
        if continuity_text:
            parts.append("===== 连续性约束（务必遵守，不得违反）=====")
            parts.append(continuity_text)
        hard = [c for c in active_views if c.strength == "hard"]
        if hard:
            parts.append("===== ACTIVE CONTINUITY CONSTRAINTS =====")
            parts.append("\n".join(f"[HARD][{c.id}] {c.content}" for c in hard))
        if conflict_reports:
            parts.append("===== UNRESOLVED CONTINUITY CONFLICTS =====")
            parts.append("\n".join(f"{r.conflict_id}: {r.constraint_a} vs {r.constraint_b}" for r in conflict_reports))
        if threads_text:
            parts.append("===== 故事线脉络（本章需推进的线）=====")
            parts.append(threads_text)
        parts.append("===== 故事大纲（节选）=====")
        parts.append(outline_text)
        if summaries_block:
            parts.append("===== 前情提要（已发生章节摘要）=====")
            parts.append(summaries_block)
        if prev_text:
            parts.append("===== 上一章结尾原文（用于衔接）=====")
            parts.append(prev_text)
        if ideas_text:
            parts.append("===== 可用灵感 idea（可酌情融入本章）=====")
            parts.append(ideas_text)
        if rag_text:
            parts.append("===== RAG 检索到的相关资料（仅作事实参考）=====")
            parts.append(rag_text)
        parts.append("===== 本章写作计划 =====")
        parts.append(current)
        deterministic_sources = []
        for sid, stype, sref in [
            ("manifesto", "manifesto", "manifesto"),
            ("bible", "bible", "bible.json"),
            ("world", "world", "world.json"),
            ("continuity", "continuity", "continuity.json"),
            ("threads", "threads", "threads.json"),
            ("outline", "outline", "outline.json"),
        ]:
            deterministic_sources.append({"source_id": sid, "source_type": stype, "source_ref": sref, "selection_reason": "deterministic"})
        if summaries_block:
            deterministic_sources.append({"source_id": "recent_summaries", "source_type": "summary", "source_ref": "chapters/summaries.json", "selection_reason": "deterministic"})
        if prev_text:
            deterministic_sources.append({"source_id": f"chapter:{done_ids[-1]}:tail", "source_type": "chapter_tail", "source_ref": done_ids[-1], "selection_reason": "deterministic"})
        idea_thread_links = {i["source_ref"]: i.get("thread_ids", []) for i in selected_ideas}
        used_thread_ids = sorted({x for i in selected_ideas for x in i.get("thread_ids", [])})
        thread_snapshot = [{"thread_id": t.id, "chapter_ids": sorted({n.chapter_id for n in t.nodes if n.chapter_id})} for t in self.threads.threads if t.id in used_thread_ids]
        conflict_snapshot = [{"conflict_id": r.conflict_id, "constraint_a": r.constraint_a, "constraint_b": r.constraint_b, "status": r.status} for r in conflict_reports]
        return ContextBundle(text="\n\n".join(parts), deterministic_sources=deterministic_sources,
            selected_ideas=selected_ideas, retrieved_sources=retrieved_sources,
            constraints=[{"constraint_id": c.id, "type": c.type, "strength": c.strength, "content": c.content, "source_chapter": c.source_chapter, "status": c.status, "supersedes": c.supersedes} for c in active_views], threads=thread_snapshot, conflicts=conflict_snapshot,
            confirmations=[{"confirmation_id": r.id, "conflict_id": r.conflict_id, "action": r.action, "timestamp": r.timestamp, "author": r.author, "note": r.note} for r in confirmations])

    def _compact_outline(self, chapters) -> str:  # type: ignore[no-untyped-def]
        lines = []
        for v in self.outline.volumes:
            vch = [c for c in v.chapters if c in chapters]
            if not vch:
                continue
            lines.append(f"《{v.title or v.volume_id}》")
            for c in vch:
                status = (
                    "✓"
                    if c.status in (ChapterStatus.done, ChapterStatus.reviewed)
                    else "·"
                )
                lines.append(f"  {status} {c.chapter_id} {c.title}：{c.beat}")
        return "\n".join(lines) if lines else "(暂无)"

    def _format_summaries(self, chapter_ids: list[str]) -> str:
        if not chapter_ids:
            return ""
        lines = []
        for cid in chapter_ids:
            s = self.store.summaries.get(cid)
            if s:
                lines.append(f"【{cid} {s.title}】{s.summary}")
        return "\n".join(lines)
