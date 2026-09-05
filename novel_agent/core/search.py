"""向量库 + 全文/语义搜索。

向量库用 numpy 存储到 embeddings/ 目录（vec.npy + index.json）。
覆盖：章节正文/摘要、设定集条目、连续性条目、世界观、idea。
支持：关键词全文搜索（零依赖）+ 语义搜索（embedding 余弦相似）+ 伏笔反查。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..llm.embedding import EmbeddingBackend


@dataclass
class Doc:
    """一个可被检索的文档片段。"""

    id: str  # 唯一 id
    kind: str  # chapter | summary | character | location | faction | item | lore | world | idea | foreshadow | fact | promise
    ref: str  # 引用定位（如 chapter_id、bible 条目 id）
    text: str  # 文本内容
    title: str = ""  # 标题（展示用）
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Hit:
    doc: Doc
    score: float
    snippet: str = ""  # 关键词命中时的高亮片段


class VectorIndex:
    """numpy 向量索引：vec.npy + index.json。"""

    def __init__(self, embed_dir: Path, dim: int = 1024) -> None:
        self.dir = embed_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.vec_path = self.dir / "vec.npy"
        self.meta_path = self.dir / "index.json"
        self.dim = dim
        self.vectors: np.ndarray | None = None
        self.ids: list[str] = []
        if self.vec_path.exists() and self.meta_path.exists():
            self.vectors = np.load(self.vec_path)
            self.ids = json.loads(self.meta_path.read_text(encoding="utf-8")).get(
                "ids", []
            )

    def _save(self) -> None:
        if self.vectors is not None:
            np.save(self.vec_path, self.vectors)
        self.meta_path.write_text(
            json.dumps({"ids": self.ids}, ensure_ascii=False), encoding="utf-8"
        )

    def upsert(self, doc_id: str, vec: list[float]) -> None:
        vec_arr = np.array([vec], dtype=np.float32)
        if doc_id in self.ids:
            i = self.ids.index(doc_id)
            self.vectors[i] = vec_arr[0]
        else:
            if self.vectors is None or len(self.vectors) == 0:
                self.vectors = vec_arr
            else:
                self.vectors = np.vstack([self.vectors, vec_arr])
            self.ids.append(doc_id)
        self._save()

    def remove(self, doc_id: str) -> None:
        if doc_id not in self.ids or self.vectors is None:
            return
        i = self.ids.index(doc_id)
        self.ids.pop(i)
        self.vectors = np.delete(self.vectors, i, axis=0)
        self._save()

    def search(self, query_vec: list[float], top_k: int = 5) -> list[tuple[str, float]]:
        if self.vectors is None or len(self.ids) == 0:
            return []
        q = np.array(query_vec, dtype=np.float32)
        sims = (self.vectors @ q) / (
            np.linalg.norm(self.vectors, axis=1) * np.linalg.norm(q) + 1e-9
        )
        order = np.argsort(-sims)[:top_k]
        return [(self.ids[i], float(sims[i])) for i in order]


class SearchEngine:
    """全文 + 语义搜索 + 伏笔反查。"""

    def __init__(self, project_dir: Path) -> None:
        self.dir = project_dir
        self.embed_dir = project_dir / "embeddings"
        self.docs: dict[str, Doc] = {}  # id -> Doc
        self._index_path = self.embed_dir / "docs.json"
        self._manifest_path = self.embed_dir / "manifest.json"
        self._load_docs()

    def _source_fingerprints(self, project_dir: Path | None = None) -> dict[str, str]:
        """指纹化项目持久化文件，包含动态章节文件。"""
        root = project_dir or self.dir
        files = [p for p in root.glob("*.json") if p.name != "manifest.json"]
        chdir = root / "chapters"
        if chdir.exists():
            files.extend(chdir.rglob("*.md"))
            files.extend(chdir.glob("summaries.json"))
        return {str(p.relative_to(root)): f"{p.stat().st_mtime_ns}:{p.stat().st_size}" for p in sorted(set(files))}

    def _manifest(self) -> dict[str, Any] | None:
        if not self._manifest_path.exists():
            return None
        try:
            return json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def consistency_check(self) -> tuple[bool, str]:
        """验证 docs、向量元数据和向量矩阵是否一致。"""
        vi = VectorIndex(self.embed_dir)
        if vi.vectors is None:
            return True, "no vectors"
        if len(self.docs) != len(vi.ids) or len(vi.ids) != len(vi.vectors):
            return False, "docs/index/vectors count mismatch"
        if set(self.docs) != set(vi.ids):
            return False, "docs/index ID mismatch"
        return True, "ok"

    def is_stale(self, *, vector_model: str = "") -> bool:
        m = self._manifest()
        if not m:
            return True
        if m.get("sources") != self._source_fingerprints():
            return True
        if m.get("doc_count") != len(self.docs):
            return True
        ok, _ = self.consistency_check()
        if not ok:
            return True
        if vector_model and m.get("vector_model", "") != vector_model:
            return True
        return False

    def ensure_index_fresh(self, *, bible, continuity, world, ideas, store,
                           project_dir: Path, embedder: EmbeddingBackend | None = None) -> bool:
        """必要时全量重建索引；返回是否重建。"""
        model = getattr(embedder, "model", "") if embedder else ""
        if not self.is_stale(vector_model=model):
            return False
        self.index_project(bible=bible, continuity=continuity, world=world,
                           ideas=ideas, store=store, project_dir=project_dir,
                           embedder=embedder, vector_model=model)
        return True

    def _load_docs(self) -> None:
        if self._index_path.exists():
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
            for d in data.get("docs", []):
                doc = Doc(**d)
                self.docs[doc.id] = doc

    def _save_docs(self) -> None:
        self.embed_dir.mkdir(parents=True, exist_ok=True)
        self._index_path.write_text(
            json.dumps(
                {"docs": [d.__dict__ for d in self.docs.values()]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    # ---- 索引构建 ----
    def index_project(
        self,
        *,
        bible,
        continuity,
        world,
        ideas,
        store,
        project_dir: Path,
        embedder: EmbeddingBackend | None = None,
        vector_model: str = "",
    ) -> dict[str, int]:
        """从知识库重建文档索引（文本部分）。embedder 非 None 时同时重建向量。"""
        from ..core.outline import ChapterStatus  # noqa: F401

        self.docs.clear()
        counts: dict[str, int] = {}

        def add(
            doc_id: str, kind: str, ref: str, text: str, title: str = "", **meta
        ) -> None:
            if not text.strip():
                return
            self.docs[doc_id] = Doc(
                id=doc_id, kind=kind, ref=ref, text=text, title=title, meta=meta
            )
            counts[kind] = counts.get(kind, 0) + 1

        def chunk_text(text: str, *, size: int = 900, overlap: int = 140) -> list[str]:
            text = text.strip()
            if not text:
                return []
            if len(text) <= size:
                return [text]
            parts: list[str] = []
            start = 0
            while start < len(text):
                end = min(len(text), start + size)
                parts.append(text[start:end])
                if end >= len(text):
                    break
                start = max(end - overlap, start + 1)
            return parts

        # 章节正文 + 摘要（正文按片段切分，避免整章过长导致检索粒度太粗）
        for cid in store.ordered_ids():
            ch = store.read_chapter(project_dir, cid)
            if ch:
                for i, chunk in enumerate(chunk_text(ch.content), start=1):
                    add(
                        f"chapter:{cid}:chunk:{i}",
                        "chapter_chunk",
                        cid,
                        chunk,
                        f"《{ch.title}》#{i}",
                        chunk_index=i,
                        chunk_count=len(chunk_text(ch.content)),
                    )
            s = store.summaries.get(cid)
            if s:
                add(f"summary:{cid}", "summary", cid, s.summary, f"摘要 {cid}")

        # 设定集
        for c in bible.characters:
            add(
                f"character:{c.id}",
                "character",
                c.id,
                f"{c.name}：{c.summary} {c.background} {c.personality} {c.motivation}",
                c.name,
            )
        for l in bible.locations:
            add(
                f"location:{l.id}",
                "location",
                l.id,
                f"{l.name}：{l.summary} {l.geography}",
                l.name,
            )
        for f in bible.factions:
            add(
                f"faction:{f.id}",
                "faction",
                f.id,
                f"{f.name}：{f.summary} {f.goals}",
                f.name,
            )
        for it in bible.items:
            add(
                f"item:{it.id}",
                "item",
                it.id,
                f"{it.name}：{it.summary} {it.power}",
                it.name,
            )
        for lo in bible.lore:
            add(
                f"lore:{lo.id}",
                "lore",
                lo.id,
                f"{lo.name}：{lo.summary} {lo.description}",
                lo.name,
            )

        # 连续性：伏笔/事实/承诺
        for fs in continuity.foreshadows:
            add(
                f"foreshadow:{fs.id}",
                "foreshadow",
                fs.id,
                f"伏笔：{fs.description}",
                fs.id,
                chapter=fs.chapter_id,
                status=fs.status.value,
            )
        for f in continuity.facts:
            add(
                f"fact:{f.id}",
                "fact",
                f.id,
                f"既定事实[{f.category}]：{f.content}",
                f.id,
                chapter=f.chapter_id,
            )
        for p in continuity.promises:
            if not p.fulfilled:
                add(
                    f"promise:{p.id}",
                    "promise",
                    p.id,
                    f"承诺：{p.maker}→{p.receiver}：{p.content}",
                    p.id,
                    chapter=p.chapter_id,
                )

        # 世界观
        for e in world.elements:
            add(
                f"world:{e.id}",
                "world",
                e.id,
                f"{e.name}：{e.summary} {e.detail}",
                e.name,
                category=e.category.value,
            )

        # idea
        for idea in ideas.ideas:
            add(
                f"idea:{idea.id}",
                "idea",
                idea.id,
                f"{idea.title}：{idea.content}",
                idea.title,
                status=idea.status.value,
            )

        self._save_docs()

        # 重建向量
        if embedder is not None:
            vi = VectorIndex(self.embed_dir, embedder.dim)
            vi.vectors = None
            vi.ids = []
            # 批量 embed（每批 16 条）
            doc_list = list(self.docs.values())
            batch = 16
            for i in range(0, len(doc_list), batch):
                chunk = doc_list[i : i + batch]
                texts = [d.text[:1500] for d in chunk]  # 截断超长文本
                vecs = embedder.embed(texts)
                for d, v in zip(chunk, vecs):
                    vi.upsert(d.id, v)
            counts["vectors"] = len(doc_list)
        else:
            # 文本索引重建时清除旧向量，避免 docs 与 vectors 属于不同 generation。
            for stale in (self.embed_dir / "vec.npy", self.embed_dir / "index.json"):
                if stale.exists():
                    stale.unlink()

        ok, reason = self.consistency_check()
        if not ok:
            raise RuntimeError(f"索引一致性检查失败: {reason}")
        manifest = {
            "version": 1,
            "sources": self._source_fingerprints(project_dir),
            "doc_count": len(self.docs),
            "vector_count": len(VectorIndex(self.embed_dir).ids),
            "vector_model": vector_model or (getattr(embedder, "model", "") if embedder else ""),
        }
        self._manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return counts

    # ---- 关键词搜索（零依赖）----
    def search_keyword(
        self, query: str, *, kinds: list[str] | None = None, limit: int = 20
    ) -> list[Hit]:
        query = query.strip()
        if not query:
            return []
        # 按字符 n-gram 匹配（中文友好）
        ql = query.lower()
        hits: list[Hit] = []
        for doc in self.docs.values():
            if kinds and doc.kind not in kinds:
                continue
            text_l = doc.text.lower()
            title_l = doc.title.lower()
            if query in doc.text or query in doc.title:
                score = 3.0 + (1.0 if query in title_l else 0.0)
            elif ql in text_l or ql in title_l:
                score = 2.0
            else:
                # 子串部分匹配
                chars = [c for c in query if c.strip()]
                matched = sum(1 for c in chars if c in text_l or c in title_l)
                if matched / max(len(chars), 1) >= 0.6:
                    score = 1.0 * matched / max(len(chars), 1)
                else:
                    continue
            snippet = self._snippet(doc.text, query)
            hits.append(Hit(doc=doc, score=score, snippet=snippet))
        hits.sort(key=lambda h: -h.score)
        return hits[:limit]

    @staticmethod
    def _snippet(text: str, query: str, width: int = 60) -> str:
        i = text.find(query)
        if i < 0:
            return text[:width]
        start = max(0, i - width // 2)
        end = min(len(text), i + len(query) + width // 2)
        pre = "…" if start > 0 else ""
        suf = "…" if end < len(text) else ""
        return pre + text[start:end] + suf

    # ---- 语义搜索 ----
    def search_semantic(
        self,
        query: str,
        embedder: EmbeddingBackend,
        *,
        kinds: list[str] | None = None,
        top_k: int = 10,
    ) -> list[Hit]:
        vi = VectorIndex(self.embed_dir, embedder.dim)
        ok, reason = self.consistency_check()
        if not ok:
            raise RuntimeError(f"索引损坏，禁止语义检索: {reason}")
        if vi.vectors is None or len(vi.ids) == 0:
            return []
        qv = embedder.embed_one(query)
        results = vi.search(qv, top_k=top_k * 2)
        hits: list[Hit] = []
        for doc_id, score in results:
            doc = self.docs.get(doc_id)
            if doc is None:
                continue
            if kinds and doc.kind not in kinds:
                continue
            hits.append(
                Hit(doc=doc, score=score, snippet=self._snippet(doc.text, query))
            )
        return hits[:top_k]

    def retrieve(
        self,
        query: str,
        *,
        embedder: EmbeddingBackend | None = None,
        kinds: list[str] | None = None,
        top_k: int = 8,
    ) -> list[Hit]:
        """优先语义检索，失败或未配置 embedding 时回退到关键词检索。"""
        if embedder is not None:
            try:
                hits = self.search_semantic(query, embedder, kinds=kinds, top_k=top_k)
                if hits:
                    return hits
            except Exception:  # noqa: BLE001
                pass
        return self.search_keyword(query, kinds=kinds, limit=top_k)

    def hybrid_search(
        self, query: str, *, embedder: EmbeddingBackend | None = None,
        kinds: list[str] | None = None, top_k: int = 8,
    ) -> list[Hit]:
        """混合召回并重排：关键词精确命中 + 向量语义命中。"""
        lexical = self.search_keyword(query, kinds=kinds, limit=top_k * 3)
        semantic = []
        if embedder is not None:
            try:
                semantic = self.search_semantic(query, embedder, kinds=kinds, top_k=top_k * 3)
            except Exception:  # noqa: BLE001
                semantic = []
        merged: dict[str, Hit] = {}
        for hit in lexical:
            merged[hit.doc.id] = Hit(hit.doc, hit.score * 0.45, hit.snippet)
        for hit in semantic:
            old = merged.get(hit.doc.id)
            score = hit.score * 0.55
            merged[hit.doc.id] = Hit(hit.doc, (old.score if old else 0.0) + score, hit.snippet)
        # 类型先验提升事实/连续性资料，同时避免同一 ref 占满结果。
        priors = {"foreshadow": 0.12, "fact": 0.10, "promise": 0.10, "summary": 0.06}
        ranked = sorted(merged.values(), key=lambda h: -(h.score + priors.get(h.doc.kind, 0)))
        selected: list[Hit] = []
        refs: set[str] = set()
        for hit in ranked:
            if hit.doc.ref in refs and hit.doc.kind == "chapter_chunk":
                continue
            selected.append(hit)
            refs.add(hit.doc.ref)
            if len(selected) >= top_k:
                break
        return selected

    # ---- 伏笔反查 ----
    def find_foreshadow_refs(self, keyword: str) -> list[Hit]:
        """根据关键词反查伏笔/相关章节。"""
        return self.search_keyword(
            keyword, kinds=["foreshadow", "chapter", "summary", "fact"]
        )
