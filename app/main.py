from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.auth import SessionManager
from app.config import Settings, load_settings
from app.models import CreateTaskRequest, TaskLogResponse
from app.services.files import (
    SUBTITLE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    build_output_path,
    choose_output_path,
    find_matching_subtitle,
    list_media_entries,
    resolve_media_path,
    validate_media_file,
)
from app.services.subtitle_tools import shift_subtitle_bytes
from app.services.subtitle_tools import shift_subtitle_file
from app.services.subtitle_tools import resolve_shift_save_path, save_shifted_subtitle
from app.services.tasks import TaskManager


def _save_uploaded_file(work_root: Path, upload: UploadFile, task_id: str, kind: str) -> Path:
    if not upload.filename:
        raise ValueError(f"缺少{kind}文件")
    suffix = Path(upload.filename).suffix.lower()
    allowed = VIDEO_EXTENSIONS if kind == "视频" else SUBTITLE_EXTENSIONS
    if suffix not in allowed:
        raise ValueError(f"{kind}文件格式不受支持")
    upload_dir = work_root / "uploads" / task_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / upload.filename
    with destination.open("wb") as handle:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    return destination


def create_app(settings: Settings) -> FastAPI:
    base_dir = Path(__file__).resolve().parent.parent
    app = FastAPI(title="ffsubsync Web", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.session_manager = SessionManager(settings)
    app.state.task_manager = TaskManager(settings.max_concurrent_tasks)
    templates = Jinja2Templates(directory=str(base_dir / "templates"))
    app.state.templates = templates
    app.mount("/static", StaticFiles(directory=str(base_dir / "static")), name="static")

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        public_paths = {"/login"}
        if request.url.path.startswith("/static") or request.url.path in public_paths:
            return await call_next(request)

        session_manager: SessionManager = request.app.state.session_manager
        if session_manager.is_authenticated(request):
            return await call_next(request)

        if request.url.path.startswith("/api/"):
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Authentication required"})
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @app.post("/login")
    async def login(request: Request, password: str = Form(...)):
        session_manager: SessionManager = request.app.state.session_manager
        if not session_manager.authenticate(password):
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "口令错误，请重试。"},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        session_manager.set_session(response)
        return response

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "index.html",
            {"media_root": str(settings.media_root), "default_max_offset_seconds": 60},
        )

    @app.get("/subtitle-tools", response_class=HTMLResponse)
    async def subtitle_tools_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "subtitle_tools.html", {})

    @app.get("/tasks", response_class=HTMLResponse)
    async def tasks_page(request: Request) -> HTMLResponse:
        task_manager: TaskManager = request.app.state.task_manager
        tasks = [task.to_summary() for task in await task_manager.list_tasks()]
        return templates.TemplateResponse(request, "tasks.html", {"tasks": tasks})

    @app.get("/tasks/{task_id}", response_class=HTMLResponse)
    async def task_page(request: Request, task_id: str) -> HTMLResponse:
        task_manager: TaskManager = request.app.state.task_manager
        try:
            task = await task_manager.get_task(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Task not found") from exc
        return templates.TemplateResponse(request, "task.html", {"task_id": task_id, "task": task.to_summary()})

    @app.get("/api/files")
    async def files_api(
        request: Request,
        kind: str = Query(..., pattern="^(video|subtitle)$"),
        dir: str = Query(default=""),
        sort_by: str = Query(default="name", pattern="^(name|modified|size)$"),
        order: str = Query(default="asc", pattern="^(asc|desc)$"),
        search: str = Query(default=""),
    ) -> JSONResponse:
        try:
            payload = list_media_entries(request.app.state.settings, kind, dir, sort_by=sort_by, order=order, search=search)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload)

    @app.get("/api/subtitles/match")
    async def match_subtitle_api(request: Request, video_path: str = Query(..., min_length=1)) -> JSONResponse:
        try:
            match = find_matching_subtitle(request.app.state.settings, video_path)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"match": match})

    @app.post("/api/tasks")
    async def create_task_api(
        request: Request,
        video_path: str = Form(default=""),
        subtitle_path: str = Form(default=""),
        subtitle_mode: str = Form(default="media"),
        output_name: str = Form(default=""),
        encoding: str = Form(default=""),
        max_offset_seconds: str = Form(default=""),
        no_fix_framerate: bool = Form(default=False),
        gss: bool = Form(default=False),
        subtitle_file: UploadFile | None = File(default=None),
    ) -> JSONResponse:
        payload = CreateTaskRequest(
            video_path=video_path or "__media__",
            subtitle_path=subtitle_path or "__dynamic__",
            output_name=output_name.strip() or None,
            encoding=encoding.strip() or None,
            max_offset_seconds=int(max_offset_seconds) if max_offset_seconds.strip() else None,
            no_fix_framerate=no_fix_framerate,
            gss=gss,
        )
        task_manager: TaskManager = request.app.state.task_manager
        source_type = "media"

        try:
            temp_task_id = uuid4().hex
            video_real_path = validate_media_file(request.app.state.settings, video_path, "video")
            if subtitle_mode == "upload":
                source_type = "upload"
                if subtitle_file is None or not getattr(subtitle_file, "filename", ""):
                    raise ValueError("请上传字幕文件")
                subtitle_real_path = _save_uploaded_file(settings.work_root, subtitle_file, temp_task_id, "字幕")
            else:
                subtitle_real_path = validate_media_file(request.app.state.settings, subtitle_path, "subtitle")

            if source_type == "media":
                output_real_path = build_output_path(
                    request.app.state.settings,
                    video_path,
                    subtitle_path,
                    payload.output_name,
                )
            else:
                output_real_path = choose_output_path(video_real_path, subtitle_real_path.suffix, payload.output_name)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        task = await task_manager.create_task(payload, video_real_path, subtitle_real_path, output_real_path, source_type)
        return JSONResponse({"task_id": task.task_id, "status": task.status})

    @app.get("/api/tasks")
    async def list_tasks_api(request: Request) -> JSONResponse:
        task_manager: TaskManager = request.app.state.task_manager
        tasks = [task.to_summary().model_dump(mode="json") for task in await task_manager.list_tasks()]
        return JSONResponse({"tasks": tasks})

    @app.get("/api/tasks/{task_id}")
    async def get_task_api(request: Request, task_id: str) -> JSONResponse:
        task_manager: TaskManager = request.app.state.task_manager
        try:
            task = await task_manager.get_task(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Task not found") from exc
        return JSONResponse(task.to_summary().model_dump(mode="json"))

    @app.get("/api/tasks/{task_id}/log")
    async def get_task_log_api(request: Request, task_id: str) -> JSONResponse:
        task_manager: TaskManager = request.app.state.task_manager
        try:
            task = await task_manager.get_task(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Task not found") from exc
        response = TaskLogResponse(task_id=task_id, status=task.status, progress=task.progress, log=task.log_text())
        return JSONResponse(response.model_dump(mode="json"))

    @app.post("/api/tasks/{task_id}/stop")
    async def stop_task_api(request: Request, task_id: str) -> JSONResponse:
        task_manager: TaskManager = request.app.state.task_manager
        try:
            task = await task_manager.stop_task(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Task not found") from exc
        return JSONResponse(task.to_summary().model_dump(mode="json"))

    @app.get("/api/tasks/{task_id}/download")
    async def download_task_output_api(request: Request, task_id: str) -> StreamingResponse:
        task_manager: TaskManager = request.app.state.task_manager
        try:
            task = await task_manager.get_task(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Task not found") from exc
        output_path = Path(task.output_path)
        if not task.can_download_output or not output_path.exists():
            raise HTTPException(status_code=404, detail="Output not available for download")
        headers = {"Content-Disposition": f'attachment; filename="{output_path.name}"'}
        return StreamingResponse(iter([output_path.read_bytes()]), media_type="application/octet-stream", headers=headers)

    @app.post("/api/subtitles/shift")
    async def shift_subtitle_api(
        request: Request,
        subtitle_mode: str = Form(default="upload"),
        subtitle_path: str = Form(default=""),
        subtitle_file: UploadFile | None = File(default=None),
        save_mode: str = Form(default="download"),
        save_dir: str = Form(default=""),
        offset_seconds: float = Form(...),
    ):
        try:
            source_filename: str
            if subtitle_mode == "media":
                source_path = validate_media_file(request.app.state.settings, subtitle_path, "subtitle")
                filename, shifted_content = shift_subtitle_file(
                    source_path,
                    offset_seconds,
                    request.app.state.settings.work_root,
                )
                source_filename = source_path.name
            else:
                if subtitle_file is None:
                    raise ValueError("请上传字幕文件")
                filename, shifted_content = shift_subtitle_bytes(
                    subtitle_file.filename,
                    await subtitle_file.read(),
                    offset_seconds,
                    request.app.state.settings.work_root,
                )
                source_filename = subtitle_file.filename or "subtitle.srt"

            saved_path = None
            if save_mode in {"save", "save_and_download"}:
                output_path = resolve_shift_save_path(
                    request.app.state.settings,
                    source_filename,
                    subtitle_media_path=subtitle_path if subtitle_mode == "media" else None,
                    save_dir=save_dir if subtitle_mode == "upload" else None,
                )
                saved_path = save_shifted_subtitle(request.app.state.settings, output_path, shifted_content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if save_mode == "save":
            return JSONResponse({"saved_path": saved_path, "filename": filename})

        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        if saved_path:
            headers["X-Saved-Path"] = saved_path
        return StreamingResponse(iter([shifted_content]), media_type="application/octet-stream", headers=headers)

    return app


def build_default_app() -> FastAPI:
    try:
        settings = load_settings()
    except RuntimeError as exc:
        error_message = str(exc)

        @asynccontextmanager
        async def failing_lifespan(app: FastAPI):
            raise RuntimeError(error_message)
            yield

        return FastAPI(title="ffsubsync Web", docs_url=None, redoc_url=None, lifespan=failing_lifespan)
    return create_app(settings)


app = build_default_app()
