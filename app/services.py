import logging
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Outbox, Product
from app.vector_store import ProductVectorStore

logger = logging.getLogger(__name__)


def save_product(db: Session, product: Product, operation: str = "upsert") -> Product:
    """Transactional outbox makes SQL authoritative and vector sync recoverable."""
    product.vector_status = product.vector_status or "pending"
    product.vector_last_error = None
    db.add(product)
    db.flush()
    db.add(Outbox(product_id=product.id, operation=operation, payload={"version": product.updated_at.isoformat() if product.updated_at else "new"}))
    db.commit()
    db.refresh(product)
    process_vector_outbox(db)
    return product


def queue_vector_retry(db: Session, product: Product, operation: str = "upsert") -> Product:
    """Re-queue a product for vector sync after Mesh/outage failures."""
    if not product.active and operation == "upsert":
        operation = "delete"
    product.vector_status = "pending"
    product.vector_last_error = None
    db.add(product)
    db.add(Outbox(product_id=product.id, operation=operation, payload={"retry": True}))
    db.commit()
    process_vector_outbox(db)
    db.refresh(product)
    return product


def process_vector_outbox(db: Session, limit: int = 50) -> int:
    jobs = db.scalars(select(Outbox).where(Outbox.processed_at.is_(None)).order_by(Outbox.id).limit(limit)).all()
    store = ProductVectorStore()
    processed = 0
    for job in jobs:
        try:
            product = db.get(Product, job.product_id)
            if job.operation == "delete" or not product:
                store.delete(job.product_id)
                if product:
                    product.vector_status = "synced"
                    product.vector_last_error = None
            else:
                store.upsert(product)
                product.vector_status = "synced"
                product.vector_last_error = None
            job.processed_at = datetime.now(timezone.utc)
            processed += 1
        except Exception as exc:
            message = str(exc)[:500]
            logger.warning("Vector outbox job %s failed for product %s: %s", job.id, job.product_id, message)
            job.attempts += 1
            job.payload = {**(job.payload or {}), "last_error": message}
            if (product := db.get(Product, job.product_id)):
                product.vector_status = "error"
                product.vector_last_error = message
        db.commit()
    return processed
