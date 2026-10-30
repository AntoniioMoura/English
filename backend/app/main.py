from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, db
from .api.listening_routes import router as listening_router
from .api.recall_routes import router as recall_router
from .api.routes import router
from .domain.rules import RuleViolation
from .services import listening_downloads, listening_media, listening_translation, recall_service
from .services.exercise_service import NotFound

FRONTEND_DIST = config.BACKEND_DIR.parent / "frontend" / "dist"


def create_app(db_path: Path | str | None = None, videos_dir: Path | None = None, listening_cache_dir: Path | None = None,
               inline_worker: bool = False) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = db.init_db(app.state.db_path)
        recall_service.backfill_reviews(conn)  # revisões faltantes de erros já avaliados
        listening_media.recover_interrupted(conn)
        listening_downloads.recover_interrupted(conn)
        listening_translation.recover_interrupted(conn)
        conn.close()
        yield

    app = FastAPI(title="English Builder", lifespan=lifespan)
    app.state.db_path = db_path or config.DB_PATH
    app.state.videos_dir = Path(videos_dir or config.VIDEOS_DIR)
    app.state.listening_worker = listening_media.ListeningWorker(
        app.state.db_path, app.state.videos_dir, Path(listening_cache_dir or config.LISTENING_CACHE_DIR), inline_worker)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RuleViolation)
    async def _rule_violation(_: Request, exc: RuleViolation):
        return JSONResponse(status_code=exc.http_status, content={"detail": {"code": exc.code, "message": exc.message}})

    @app.exception_handler(NotFound)
    async def _not_found(_: Request, exc: NotFound):
        return JSONResponse(status_code=404, content={"detail": {"code": "not_found", "message": str(exc)}})

    app.include_router(router)
    app.include_router(recall_router)
    app.include_router(listening_router)

    # Em produção local (`npm run build`), a própria API serve a interface.
    if FRONTEND_DIST.exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            file = FRONTEND_DIST / path
            if path and file.is_file():
                return FileResponse(file)
            # Sem cache para a página: depois de uma atualização o navegador pega a versão nova
            # (os arquivos em /assets mudam de nome a cada build).
            return FileResponse(FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
