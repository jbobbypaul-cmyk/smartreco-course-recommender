from contextlib import asynccontextmanager
from datetime import timezone
from pathlib import Path
from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from app.agent import maybe_generate
from app.config import get_settings
from app.db import Base, SessionLocal, engine, get_db
from app.models import Event, Outbox, Product, Recommendation, Role, User
from app.schemas import EventBatch
from app.scheduler import daily_digest, smtp_status, start_scheduler
from app.security import create_token, decode_token, hash_password, verify_password
from app.services import process_vector_outbox, queue_vector_retry, save_product

ROOT = Path(__file__).parent
templates = Jinja2Templates(directory=ROOT / "templates")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    payload = decode_token(request.cookies.get("session", ""))
    user = db.get(User, int(payload["sub"])) if payload else None
    if not user: raise HTTPException(401, "Sign in required")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != Role.admin: raise HTTPException(403, "Admin access required")
    return user


def ensure_schema() -> None:
    """Lightweight SQLite-safe migrations for demo databases."""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(products)")).fetchall()}
        if "vector_last_error" not in cols:
            conn.execute(text("ALTER TABLE products ADD COLUMN vector_last_error TEXT"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    ensure_schema()
    s = get_settings()
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.email == s.admin_email)):
            db.add(User(email=s.admin_email, password_hash=hash_password(s.admin_password), role=Role.admin)); db.commit()
    scheduler = start_scheduler()
    yield
    if scheduler: scheduler.shutdown(wait=False)


app = FastAPI(title="SmartReco", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/health")
def health(): return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    products = db.scalars(select(Product).where(Product.active.is_(True)).order_by(Product.updated_at.desc())).all()
    payload = decode_token(request.cookies.get("session", "")); user = db.get(User, int(payload["sub"])) if payload else None
    reco = db.scalar(select(Recommendation).where(Recommendation.user_id == user.id).order_by(Recommendation.created_at.desc())) if user else None
    reco_products = [db.get(Product, pid) for pid in reco.product_ids] if reco else None
    reco_products = reco_products or []
    evidence = reco.evidence if reco and isinstance(reco.evidence, dict) else {}
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "products": products,
            "user": user,
            "reco": reco,
            "reco_products": reco_products,
            "reco_trace": evidence.get("trace") or [],
            "reco_why": evidence.get("why") or "",
            "reco_selected": evidence.get("selected") or [],
        },
    )


@app.post("/register")
def register(email: str = Form(), password: str = Form(), db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == email.lower())): raise HTTPException(409, "Email already registered")
    user = User(email=email.lower(), password_hash=hash_password(password)); db.add(user); db.commit(); db.refresh(user)
    response = RedirectResponse("/", 303); response.set_cookie("session", create_token(user.id, user.role.value), httponly=True, samesite="lax", secure=False); return response


@app.post("/login")
def login(email: str = Form(), password: str = Form(), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == email.lower()))
    if not user or not verify_password(password, user.password_hash): raise HTTPException(401, "Invalid credentials")
    response = RedirectResponse("/", 303); response.set_cookie("session", create_token(user.id, user.role.value), httponly=True, samesite="lax", secure=False); return response


@app.post("/logout")
def logout():
    response = RedirectResponse("/", 303); response.delete_cookie("session"); return response


@app.post("/api/events", status_code=202)
def ingest(batch: EventBatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    existing = set(db.scalars(select(Event.event_id).where(Event.event_id.in_([e.event_id for e in batch.events]))).all())
    for e in batch.events:
        if e.event_id not in existing:
            db.add(Event(event_id=e.event_id, user_id=user.id, event_type=e.event_type, product_id=e.product_id, query=e.query, dwell_ms=e.dwell_ms, metadata_json=e.metadata, occurred_at=e.occurred_at.astimezone(timezone.utc)))
    db.commit()
    return {"accepted": len(batch.events) - len(existing)}


@app.post("/api/recommendations/refresh")
def refresh(user: User = Depends(current_user), db: Session = Depends(get_db)):
    reco = maybe_generate(db, user.id)
    return {"recommendation_id": reco.id if reco else None, "status": "ready" if reco else "insufficient_signal"}


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    products = db.scalars(select(Product).order_by(Product.id.desc())).all()
    synced = sum(1 for p in products if p.vector_status == "synced")
    errored = sum(1 for p in products if p.vector_status == "error")
    pending = sum(1 for p in products if p.vector_status == "pending")
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "products": products,
            "user": user,
            "vector_synced": synced,
            "vector_errored": errored,
            "vector_pending": pending,
            "smtp": smtp_status(),
            "digest_flash": request.query_params.get("digest"),
        },
    )


@app.post("/admin/digest/send-now")
def send_digest_now(_: User = Depends(admin_user)):
    if not smtp_status()["configured"]:
        return RedirectResponse("/admin?digest=smtp_missing", 303)
    summary = daily_digest(force=True)
    if summary["failed"]:
        return RedirectResponse(f"/admin?digest=failed_{summary['failed']}", 303)
    return RedirectResponse(f"/admin?digest=sent_{summary['sent']}", 303)


@app.post("/admin/products")
def add_product(title: str = Form(), description: str = Form(), category: str = Form(), price: float = Form(), level: str = Form("All levels"), _: User = Depends(admin_user), db: Session = Depends(get_db)):
    save_product(db, Product(title=title, description=description, category=category, price=price, level=level))
    return RedirectResponse("/admin", 303)


@app.post("/admin/products/{product_id}/edit")
def edit_product(product_id: int, title: str = Form(), description: str = Form(), category: str = Form(), price: float = Form(), level: str = Form("All levels"), _: User = Depends(admin_user), db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product: raise HTTPException(404)
    product.title, product.description, product.category = title, description, category
    product.price, product.level, product.vector_status = price, level, "pending"
    product.vector_last_error = None
    save_product(db, product)
    return RedirectResponse("/admin", 303)


@app.post("/admin/products/{product_id}/delete")
def delete_product(product_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product: raise HTTPException(404)
    product.active = False
    product.vector_status = "pending"
    product.vector_last_error = None
    db.add(product)
    db.add(Outbox(product_id=product.id, operation="delete"))
    db.commit()
    process_vector_outbox(db)
    return RedirectResponse("/admin", 303)


@app.post("/admin/products/{product_id}/retry-vector")
def retry_product_vector(product_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product: raise HTTPException(404)
    queue_vector_retry(db, product, operation="upsert" if product.active else "delete")
    return RedirectResponse("/admin", 303)


@app.post("/admin/vectors/retry-failed")
def retry_failed_vectors(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    failed = db.scalars(select(Product).where(Product.vector_status == "error")).all()
    for product in failed:
        queue_vector_retry(db, product, operation="upsert" if product.active else "delete")
    return RedirectResponse("/admin", 303)
