"""知识检索器 — 面向客服场景的高层封装"""

from pathlib import Path

from .store import KnowledgeStore, Document


class Retriever:
    """知识库检索器

    用法:
        retriever = Retriever()
        retriever.load_faqs("data/faqs.json")  # 可选: 从文件加载
        retriever.add_faq("退货政策？", "30天无理由退货...")

        result = retriever.ask("怎么退货")
        if result:
            print(result["answer"])
        else:
            print("未找到相关答案，转人工")
    """

    def __init__(self, store: KnowledgeStore | None = None):
        self.store = store or KnowledgeStore(name="customer_service")

    def add_faq(self, question: str, answer: str, tags: list[str] | None = None) -> None:
        self.store.add_faq(question, answer, tags)

    def load_faqs(self, path: str | Path) -> None:
        """从 JSON 文件批量加载 FAQ

        JSON 格式:
        [
            {"question": "发货时间？", "answer": "48小时内发货...", "tags": ["物流"]},
            ...
        ]
        """
        import json
        path = Path(path)
        if not path.exists():
            print(f"  ⚠ FAQ 文件不存在: {path}")
            return
        faqs = json.loads(path.read_text(encoding="utf-8"))
        self.store.add_bulk_faqs(faqs)
        print(f"  ✓ 加载 {len(faqs)} 条 FAQ")

    def ask(self, query: str, threshold: float = 0.15) -> dict | None:
        """检索最佳匹配 FAQ

        Returns:
            {"question": "...", "answer": "...", "score": 0.85} 或 None
        """
        results = self.store.search_faq(query, top_k=3)
        if not results or results[0][1] < threshold:
            return None

        doc, score = results[0]
        return {
            "question": doc.question,
            "answer": doc.content,
            "score": score,
            "tags": doc.metadata.get("tags", []),
        }

    def ask_all(self, query: str, threshold: float = 0.1) -> list[dict]:
        """返回所有匹配结果"""
        results = self.store.search_faq(query, top_k=5)
        return [
            {
                "question": doc.question,
                "answer": doc.content,
                "score": score,
                "tags": doc.metadata.get("tags", []),
            }
            for doc, score in results
            if score >= threshold
        ]

    def __len__(self) -> int:
        return len(self.store)
