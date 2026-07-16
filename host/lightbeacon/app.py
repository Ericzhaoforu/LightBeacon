from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Annotated, AsyncIterator

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .auth import SessionManager, verify_password
from .config import Settings
from .database import Database
from .events import EventBroker
from .models import EffectRequest, Layout, LoginRequest, OtaCreateResponse
from .ota import OtaError, OtaManager
from .udp_controller import UdpController

COOKIE_NAME = "lb_session"


def _configure_logging(settings: Settings) -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(handler, RotatingFileHandler) for handler in root.handlers):
        handler = RotatingFileHandler(
            settings.log_dir / "lightbeacon.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root.addHandler(handler)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        current = resolved or Settings.from_env()
        _configure_logging(current)
        database = Database(current.data_dir / "lightbeacon.sqlite3")
        database.initialize()
        events = EventBroker()
        udp = UdpController(current, database, events)
        auth = SessionManager(current.session_secret)
        await udp.start()
        app.state.settings = current
        app.state.database = database
        app.state.events = events
        app.state.udp = udp
        app.state.auth = auth
        app.state.ota = OtaManager(current, database, events, udp)
        try:
            yield
        finally:
            await udp.close()
            database.close()

    app = FastAPI(title="LightBeacon", version="0.1.0", lifespan=lifespan)

    def require_admin(
        request: Request, token: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None
    ) -> None:
        if not request.app.state.auth.verify(token):
            raise HTTPException(status_code=401, detail="authentication required")

    @app.get("/api/v1/health")
    async def health(request: Request) -> dict[str, object]:
        return {
            "status": "ok",
            "version": app.version,
            "session_id": request.app.state.udp.session_id,
            "udp_port": request.app.state.udp.bound_port,
        }

    @app.post("/api/v1/auth/login")
    async def login(request: Request, body: LoginRequest, response: Response) -> dict[str, str]:
        if not verify_password(body.password, request.app.state.settings.admin_password_hash):
            raise HTTPException(status_code=401, detail="invalid password")
        token = request.app.state.auth.issue()
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=request.app.state.auth.ttl_seconds,
            httponly=True,
            secure=False,
            samesite="strict",
            path="/",
        )
        request.app.state.database.audit("login", {"client": request.client.host if request.client else "unknown"})
        return {"status": "authenticated"}

    @app.post("/api/v1/auth/logout", dependencies=[Depends(require_admin)])
    async def logout(response: Response) -> dict[str, str]:
        response.delete_cookie(COOKIE_NAME, path="/")
        return {"status": "logged_out"}

    @app.get("/api/v1/nodes", dependencies=[Depends(require_admin)])
    async def nodes(request: Request) -> list[dict[str, object]]:
        return [node.model_dump(mode="json") for node in request.app.state.udp.list_nodes()]

    @app.get("/api/v1/layout", dependencies=[Depends(require_admin)])
    async def get_layout(request: Request) -> Layout:
        return request.app.state.database.get_layout()

    @app.put("/api/v1/layout", dependencies=[Depends(require_admin)])
    async def put_layout(request: Request, layout: Layout) -> Layout:
        request.app.state.database.save_layout(layout)
        await request.app.state.events.publish({"type": "layout.updated", "layout": layout.model_dump()})
        return layout

    @app.post("/api/v1/effects", dependencies=[Depends(require_admin)])
    async def effects(request: Request, effect: EffectRequest) -> dict[str, object]:
        result = await request.app.state.udp.set_effect(effect)
        return result.model_dump(mode="json")

    @app.post("/api/v1/all-off", dependencies=[Depends(require_admin)])
    async def all_off(request: Request) -> dict[str, object]:
        result = await request.app.state.udp.all_off()
        return result.model_dump(mode="json")

    @app.post(
        "/api/v1/ota",
        response_model=OtaCreateResponse,
        dependencies=[Depends(require_admin)],
    )
    async def create_ota(
        request: Request,
        firmware: Annotated[UploadFile, File()],
        targets: Annotated[str, Form()],
        version: Annotated[str, Form(min_length=1, max_length=64)],
    ) -> dict[str, object]:
        try:
            parsed_targets = json.loads(targets)
            if not isinstance(parsed_targets, list) or not all(isinstance(item, str) for item in parsed_targets):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(status_code=422, detail="targets must be a JSON list of node IDs") from None
        try:
            return await request.app.state.ota.create_job(firmware, parsed_targets, version)
        except OtaError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/ota/{job_id}", dependencies=[Depends(require_admin)])
    async def get_ota(request: Request, job_id: str) -> dict[str, object]:
        job = request.app.state.database.get_ota_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="OTA job not found")
        job.pop("token", None)
        job.pop("image_path", None)
        return job

    @app.get("/api/v1/firmware/{job_id}")
    async def download_firmware(request: Request, job_id: str, token: str = "") -> FileResponse:
        job = request.app.state.database.get_ota_job(job_id)
        supplied = token or request.headers.get("X-LightBeacon-OTA-Token", "")
        if job is None or not secrets_compare(supplied, job["token"]):
            raise HTTPException(status_code=404, detail="firmware not found")
        return FileResponse(job["image_path"], media_type="application/octet-stream", filename="firmware.bin")

    @app.websocket("/api/v1/events")
    async def websocket_events(websocket: WebSocket) -> None:
        token = websocket.cookies.get(COOKIE_NAME)
        if not websocket.app.state.auth.verify(token):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        await websocket.send_json(
            {
                "type": "snapshot",
                "nodes": [node.model_dump(mode="json") for node in websocket.app.state.udp.list_nodes()],
            }
        )
        try:
            async for event in websocket.app.state.events.subscribe():
                await websocket.send_json(event)
        except WebSocketDisconnect:
            return

    web_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if web_dist.exists():
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
    else:
        @app.get("/")
        async def root() -> JSONResponse:
            return JSONResponse(
                {"service": "LightBeacon", "message": "Build web/ with npm run build to install the console."}
            )
    return app


def secrets_compare(left: str, right: str) -> bool:
    import hmac

    return bool(left) and hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))

