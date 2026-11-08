from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router as intercom_router


def create_api_app() -> FastAPI:
    """Создает и конфигурирует экземпляр FastAPI для межботового API."""
    app = FastAPI(
        title="TownBot Intercom & Referendum API",
        version="1.0.0",
        description="REST API для взаимодействия между TownBot и ботом опросов (суды присяжных, референдумы, проверка статусов)",
        docs_url="/docs",
        redoc_url="/redoc"
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(intercom_router)

    @app.api_route("/", methods=["GET", "HEAD"], tags=["Health"])
    async def root_health():
        return {"status": "ok", "service": "TownRatushaBot"}

    @app.api_route("/health", methods=["GET", "HEAD"], tags=["Health"])
    async def health_check():
        return {"status": "ok", "service": "TownBot Cross-Bot API"}

    return app
