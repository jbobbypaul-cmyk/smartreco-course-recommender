import chromadb
from app.config import get_settings
from app.mesh import MeshClient


def product_text(p) -> str:
    return f"{p.title}\nCategory: {p.category}\nLevel: {p.level}\nPrice: ${p.price:.2f}\n{p.description}"


class ProductVectorStore:
    def __init__(self):
        self.collection = chromadb.PersistentClient(path=get_settings().chroma_path).get_or_create_collection("products")

    def upsert(self, product) -> None:
        text = product_text(product)
        vector = MeshClient().embed([text])[0]
        self.collection.upsert(
            ids=[str(product.id)],
            embeddings=[vector],
            documents=[text],
            metadatas=[{
                "category": product.category,
                "level": product.level,
                "active": bool(product.active),
                "price": float(product.price),
            }],
        )

    def delete(self, product_id: int) -> None:
        self.collection.delete(ids=[str(product_id)])

    def search(self, query: str, limit: int = 8, category: str | None = None, level: str | None = None) -> list[tuple[int, float]]:
        clauses = [{"active": True}]
        if category:
            clauses.append({"category": category})
        if level:
            clauses.append({"level": level})
        where = clauses[0] if len(clauses) == 1 else {"$and": clauses}
        result = self.collection.query(
            query_embeddings=[MeshClient().embed([query])[0]],
            n_results=limit,
            where=where,
        )
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        return [(int(pid), 1 / (1 + distance)) for pid, distance in zip(ids, distances)]
