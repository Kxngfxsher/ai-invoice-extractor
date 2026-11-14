"""HTTP API и раздача интерфейса бухгалтера."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import MAX_UPLOAD_BYTES, Settings, get_settings
from .export import build_csv, build_xlsx
from .schemas import DOC_TYPE_LABELS, InvoiceData
from .service import Conflict, InvoiceService, NotFound

STATIC_DIR = Path(__file__).resolve().parent / "static"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def create_app(settings: Settings | None = None, service: InvoiceService | None = None, reset: bool = False) -> FastAPI:
    settings = settings or get_settings()
    service = service or InvoiceService(settings)
    if settings.demo_mode and (reset or service.store.count() == 0):
        service.seed()

    app = FastAPI(title="Счёт-сканер", docs_url="/api/docs", redoc_url=None)
    app.state.service = service

    def guarded(action):
        """Переводит ошибки сервисного слоя в HTTP-коды."""
        try:
            return action()
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/config")
    def config() -> dict:
        return {
            "company": service.company["name"],
            "engine": service.engine.name,
            "engine_error": service.engine_error,
            "model": settings.model if service.engine.name == "claude" else None,
            "demo_mode": settings.demo_mode,
            "doc_types": DOC_TYPE_LABELS,
        }

    @app.get("/api/stats")
    def stats() -> dict:
        return service.stats()

    @app.get("/api/documents")
    def list_documents() -> list[dict]:
        return service.list()

    @app.post("/api/documents", status_code=201)
    def upload(file: UploadFile) -> dict:
        """Точка приёма документов: сюда же может слать вложения почтовый робот."""
        content = file.file.read(MAX_UPLOAD_BYTES + 1)
        return guarded(lambda: service.process(file.filename or "document", content))

    @app.get("/api/documents/{doc_id}")
    def get_document(doc_id: int) -> dict:
        return guarded(lambda: service.get(doc_id))

    @app.put("/api/documents/{doc_id}")
    def update_document(doc_id: int, data: InvoiceData) -> dict:
        return guarded(lambda: service.update(doc_id, data))

    @app.post("/api/documents/{doc_id}/{action}")
    def decide(doc_id: int, action: str) -> dict:
        statuses = {"approve": "approved", "reject": "rejected", "reopen": "new"}
        if action not in statuses:
            raise HTTPException(404, "Неизвестное действие")
        return guarded(lambda: service.decide(doc_id, statuses[action]))

    @app.get("/api/documents/{doc_id}/preview")
    def preview(doc_id: int) -> FileResponse:
        path = guarded(lambda: service.preview_path(doc_id))
        return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/api/export.xlsx")
    def export_xlsx(scope: str = "approved") -> Response:
        content = build_xlsx(service.export_rows(scope))
        return Response(content, media_type=XLSX_TYPE, headers={"Content-Disposition": 'attachment; filename="documents.xlsx"'})

    @app.get("/api/export.csv")
    def export_csv(scope: str = "approved") -> Response:
        content = build_csv(service.export_rows(scope))
        return Response(content, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="documents.csv"'})

    @app.get("/api/export.json")
    def export_json(scope: str = "approved") -> list[dict]:
        return [{"file": row["filename"], "status": row["status"], **row["data"]} for row in service.export_rows(scope)]

    if settings.demo_mode:

        @app.get("/api/samples")
        def samples() -> list[dict]:
            return service.samples()

        @app.post("/api/samples/{name}", status_code=201)
        def load_sample(name: str) -> dict:
            return guarded(lambda: service.load_sample(name))

        @app.post("/api/demo/reset")
        def reset_demo() -> dict:
            return {"seeded": service.seed()}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
