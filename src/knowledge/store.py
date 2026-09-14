"""简易向量知识库 — 纯 Python 实现，无需外部依赖

支持:
- TF-IDF 向量化 + 余弦相似度检索
- JSON 文档存储
- 关键词+向量混合检索
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ═══════════════════════════════════════════════════════════════════════
# TF-IDF 简易实现
# ═══════════════════════════════════════════════════════════════════════

class SimpleVectorizer:
    """简易 TF-IDF 向量化器"""

    def __init__(self):
        self.vocabulary: dict[str, int] = {}   # word → index
        self.idf: dict[int, float] = {}        # index → idf

    def _tokenize(self, text: str) -> list[str]:
        """中文+英文混合分词"""
        # 中文: 2-gram 字符级
        # 英文: 按空格/标点分词
        text = text.lower().strip()
        tokens = []

        # 提取英文单词
        en_words = re.findall(r"[a-zA-Z0-9]+", text)
        tokens.extend(en_words)

        # 中文 1-gram 和 2-gram
        cn_chars = re.findall(r"[一-鿿]", text)
        tokens.extend(cn_chars)
        for i in range(len(cn_chars) - 1):
            tokens.append(cn_chars[i] + cn_chars[i + 1])

        return tokens

    def fit(self, documents: list[str]) -> None:
        """构建词汇表和 IDF"""
        doc_count = len(documents)
        doc_freq: Counter = Counter()

        for doc in documents:
            tokens = set(self._tokenize(doc))
            for t in tokens:
                if t not in self.vocabulary:
                    self.vocabulary[t] = len(self.vocabulary)
                doc_freq[t] += 1

        for word, idx in self.vocabulary.items():
            df = doc_freq.get(word, 1)
            self.idf[idx] = math.log((doc_count + 1) / (df + 1)) + 1

    def transform(self, text: str) -> dict[int, float]:
        """将文本转为稀疏向量 {index: tfidf}"""
        tokens = self._tokenize(text)
        if not tokens:
            return {}

        tf = Counter(tokens)
        max_tf = max(tf.values()) if tf else 1

        vec: dict[int, float] = {}
        for token, count in tf.items():
            idx = self.vocabulary.get(token)
            if idx is not None and idx in self.idf:
                vec[idx] = (count / max_tf) * self.idf[idx]

        # L2 归一化
        norm = math.sqrt(sum(v ** 2 for v in vec.values()))
        if norm > 0:
            vec = {k: v / norm for k, v in vec.items()}

        return vec

    @staticmethod
    def cosine_similarity(v1: dict[int, float], v2: dict[int, float]) -> float:
        """余弦相似度"""
        if not v1 or not v2:
            return 0.0
        dot = sum(v1.get(k, 0) * v2.get(k, 0) for k in set(v1) | set(v2))
        # 已归一化，点积即余弦
        return max(0.0, min(1.0, dot))


# ═══════════════════════════════════════════════════════════════════════
# 知识库存储
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class Document:
    """知识库文档"""
    id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def question(self) -> str:
        return self.metadata.get("question", "")

    @property
    def answer(self) -> str:
        return self.content


class KnowledgeStore:
    """简易知识库

    用法:
        store = KnowledgeStore()
        store.add_faq("退货流程是什么？", "请在订单页申请退货...")
        store.add_faq("发货时间？", "下单后48小时内发货...")

        results = store.search("怎么退货", top_k=3)
        for doc, score in results:
            print(f"[{score:.2f}] {doc.question} → {doc.answer}")
    """

    def __init__(self, name: str = "default"):
        self.name = name
        self.documents: list[Document] = []
        self.vectorizer = SimpleVectorizer()
        self._vectors: list[dict[int, float]] = []
        self._fitted = False
        self._keyword_index: dict[str, set[int]] = {}  # keyword → doc indices

    def add(self, content: str, metadata: dict | None = None) -> str:
        """添加文档，返回 doc_id"""
        metadata = metadata or {}
        doc_id = metadata.get("id", f"doc_{len(self.documents):04d}")
        doc = Document(id=doc_id, content=content, metadata=metadata)
        self.documents.append(doc)
        self._fitted = False
        return doc_id

    def add_faq(self, question: str, answer: str, tags: list[str] | None = None) -> str:
        """快捷添加 FAQ"""
        return self.add(
            content=answer,
            metadata={"question": question, "tags": tags or [], "type": "faq"},
        )

    def add_bulk_faqs(self, faqs: list[dict]) -> None:
        """批量添加 FAQ
        faqs: [{"question": "...", "answer": "...", "tags": [...]}, ...]
        """
        for faq in faqs:
            self.add_faq(
                question=faq.get("question", ""),
                answer=faq.get("answer", ""),
                tags=faq.get("tags", []),
            )

    def _build_index(self) -> None:
        """构建向量索引和关键词索引"""
        if not self.documents:
            return

        texts = [d.question + " " + d.content for d in self.documents]
        self.vectorizer.fit(texts)
        self._vectors = [self.vectorizer.transform(t) for t in texts]

        # 关键词索引
        self._keyword_index = {}
        for i, doc in enumerate(self.documents):
            text = doc.question + " " + doc.content + " " + " ".join(doc.metadata.get("tags", []))
            words = set(re.findall(r"[一-鿿\w]+", text.lower()))
            for w in words:
                if w not in self._keyword_index:
                    self._keyword_index[w] = set()
                self._keyword_index[w].add(i)

        self._fitted = True

    def search(
        self,
        query: str,
        top_k: int = 5,
        vector_weight: float = 0.6,
    ) -> list[tuple[Document, float]]:
        """混合检索: 向量相似度 + 关键词匹配"""
        if not self._fitted:
            self._build_index()

        if not self.documents:
            return []

        query_vec = self.vectorizer.transform(query)
        query_keywords = set(re.findall(r"[一-鿿\w]+", query.lower()))

        scores: list[float] = []
        for i, doc_vec in enumerate(self._vectors):
            # 向量分
            vec_score = self.vectorizer.cosine_similarity(query_vec, doc_vec)

            # 关键词分
            kw_score = 0.0
            match_count = 0
            for kw in query_keywords:
                if kw in self._keyword_index and i in self._keyword_index[kw]:
                    match_count += 1
            if query_keywords:
                kw_score = match_count / len(query_keywords)

            scores.append(vector_weight * vec_score + (1 - vector_weight) * kw_score)

        # 排序取 top_k
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return [(self.documents[i], round(s, 3)) for i, s in ranked[:top_k] if s > 0.05]

    def search_faq(self, query: str, top_k: int = 3) -> list[tuple[Document, float]]:
        """搜索 FAQ，返回 (文档, 相似度)"""
        return self.search(query, top_k)

    def save(self, path: str | Path) -> None:
        """保存知识库到 JSON"""
        path = Path(path)
        data = {
            "name": self.name,
            "documents": [
                {"id": d.id, "content": d.content, "metadata": d.metadata}
                for d in self.documents
            ],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "KnowledgeStore":
        """从 JSON 加载知识库"""
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        store = cls(name=data.get("name", "loaded"))
        for d in data.get("documents", []):
            store.add(content=d["content"], metadata=d.get("metadata", {}))
        store._build_index()
        return store

    def __len__(self) -> int:
        return len(self.documents)
