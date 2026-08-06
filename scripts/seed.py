from app.db import Base, SessionLocal, engine
from app.models import Product
from app.services import save_product

DATA = [
    ("Agentic AI Systems", "Build reliable tool-using agents with planning, memory, evaluation, and human oversight.", "Artificial Intelligence", 89, "Advanced"),
    ("Practical RAG Engineering", "Design grounded retrieval systems with chunking, hybrid search, reranking, and evaluation.", "Artificial Intelligence", 69, "Intermediate"),
    ("AI Product Leadership", "Turn customer problems into measurable AI product strategy and responsible roadmaps.", "Product", 59, "Intermediate"),
    ("FastAPI in Production", "Build typed Python APIs with authentication, testing, observability, and deployment.", "Engineering", 49, "Intermediate"),
    ("Data Storytelling", "Transform analysis into clear executive narratives, dashboards, and decisions.", "Data", 39, "All levels"),
]
Base.metadata.create_all(engine)
with SessionLocal() as db:
    for title, description, category, price, level in DATA:
        save_product(db, Product(title=title, description=description, category=category, price=price, level=level))

