from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.config import settings
from app.database import Base, engine
from app.routers import (
    users,
    pdf_to_heic,
    pdf_to_long_image,
    heic_to_pdf,
    pdf_to_pptx,
    pptx_to_pdf
)
from app.services.pptx_to_pdf import cleanup_stale_dirs


Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_stale_dirs(settings.PPTX_PDF_STALE_DIR_MINUTES)
    yield


app = FastAPI(
    title="User Management API",
    version="1.0.0",
    lifespan=lifespan
)





app.include_router(users.router)
app.include_router(pdf_to_heic.router)
app.include_router(pdf_to_long_image.router)
app.include_router(heic_to_pdf.router)
app.include_router(pdf_to_pptx.router)
app.include_router(pptx_to_pdf.router)


@app.get("/")
def home():
    return {
        "message": "Hello, FastAPI!"
    }


@app.get("/about")
def about():
    return {
        "message": "User Management API",
        "version": "1.0.0"
    }
