from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings

from app.routers import (
    pdf_to_heic,
    pdf_to_long_image,
    heic_to_pdf,
    pdf_to_pptx,
    pptx_to_pdf
)
from app.services.pptx_to_pdf import cleanup_stale_dirs


@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_stale_dirs(settings.PPTX_PDF_STALE_DIR_MINUTES)
    yield


app = FastAPI(
    title="File Conversion API",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(pdf_to_heic.router)
app.include_router(pdf_to_long_image.router)
app.include_router(heic_to_pdf.router)
app.include_router(pdf_to_pptx.router)
app.include_router(pptx_to_pdf.router)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


@app.get("/about")
def about():
    return {
        "message": "File Conversion API",
        "version": "1.0.0"
    }
