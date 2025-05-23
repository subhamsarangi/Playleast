# sync_routes.py
import asyncio
import traceback

from fastapi import APIRouter, Request, BackgroundTasks, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from utils_playlist import (
    get_or_analyze_playlist,
    extract_playlist_id,
    get_playlists,
    delete_playlist,
)
from utils_sync import SyncManager, send_playlists_to_api_sync
from database import init_db

router = APIRouter()
templates = Jinja2Templates(directory="templates")

db_engine = init_db()
sync_manager = SyncManager(db_engine)


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    try:
        playlists = get_playlists()
        sync_status = request.query_params.get("sync")
        error_message = request.query_params.get("message")

        message = None
        message_type = "primary"

        if sync_status == "started":
            message = "Playlist sync started."
        elif sync_status == "error":
            message = error_message or "An error occurred during sync."
            message_type = "danger"

        # Check if there's an active sync
        active_sync = sync_manager.get_active_sync_task()

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "playlists": playlists,
                "message": message,
                "message_type": message_type,
                "active_sync": active_sync,
            },
        )
    except Exception as e:
        traceback.print_exc()
        return RedirectResponse(url="/", status_code=303)


@router.post("/analyze", response_class=HTMLResponse)
def analyze(
    request: Request, playlist_url: str = Form(...), force_refresh: bool = Form(False)
):
    try:
        playlist_id = extract_playlist_id(playlist_url)
        return RedirectResponse(
            url=f"/playlist/{playlist_id}?force_refresh={force_refresh}",
            status_code=303,
        )

    except Exception as e:
        traceback.print_exc()
        return templates.TemplateResponse(
            "index.html", {"request": request, "error": str(e)}
        )


@router.get("/playlist/{playlist_id}", response_class=HTMLResponse)
def show_playlist(request: Request, playlist_id: str, force_refresh: bool = False):
    try:
        # Fetch from database or run analysis if not found
        result = get_or_analyze_playlist(playlist_id, force_refresh)

        if "error" in result:
            return templates.TemplateResponse(
                "index.html", {"request": request, "error": result["error"]}
            )

        template_data = {
            "request": request,
            "top_videos": result["top_videos"],
            "all_videos": result["all_videos"],
            "playlist_url": result["playlist_info"]["url"],
            "playlist_id": playlist_id,
            "playlist_info": result["playlist_info"],
            "from_cache": result.get("from_cache", False),
        }

        return templates.TemplateResponse("playlist.html", template_data)

    except Exception as e:
        traceback.print_exc()
        return templates.TemplateResponse(
            "index.html", {"request": request, "error": str(e)}
        )


@router.get("/playlist/{playlist_id}/delete", response_class=RedirectResponse)
def delete_playlist_view(playlist_id: str):
    try:
        print("Trying to delete... ")
        delete_playlist(playlist_id)
        return RedirectResponse(url="/", status_code=303)
    except Exception as e:
        traceback.print_exc()
        return RedirectResponse(url="/", status_code=303)


@router.get("/sync", response_class=HTMLResponse)
async def sync_playlists(request: Request, background_tasks: BackgroundTasks):
    """Start sync process"""
    try:
        playlists = get_playlists()

        task_id = sync_manager.create_sync_task(len(playlists))
        print(f"task_id ------------------------> {task_id}")

        background_tasks.add_task(send_playlists_to_api_sync, playlists, sync_manager)

        return RedirectResponse(url="/?sync=started", status_code=303)

    except ValueError as e:
        return RedirectResponse(url="/?sync=error&message=" + str(e), status_code=303)
    except Exception as e:
        return RedirectResponse(
            url="/?sync=error&message=Failed to start sync", status_code=303
        )


@router.get("/sync/events")
async def sync_events(request: Request):
    """Server-sent events endpoint for sync updates"""

    async def event_generator():
        queue = asyncio.Queue()
        sync_manager.add_event_subscriber(queue)

        try:
            while True:
                try:
                    # Wait for event with timeout
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)

                    # Format as SSE
                    event_type = event.get("event", "message")
                    data = event.get("data", {})

                    yield f"event: {event_type}\n"
                    yield f"data: {data}\n\n"

                except asyncio.TimeoutError:
                    # Send heartbeat
                    yield f"event: heartbeat\n"
                    yield f"data: {{}}\n\n"

        except Exception as e:
            print(f"SSE Error: {e}")
        finally:
            sync_manager.remove_event_subscriber(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/sync/status")
async def get_sync_status(request: Request):
    """Get current sync status"""
    active_task = sync_manager.get_active_sync_task()
    if active_task:
        return {
            "active": True,
            "task_id": active_task.id,
            "status": active_task.status,
            "total": active_task.total_playlists,
            "processed": active_task.processed_playlists,
            "started_at": active_task.started_at.isoformat(),
        }
    else:
        return {"active": False}


@router.post("/sync/abort/{task_id}")
async def abort_sync(task_id: int):
    """Abort a sync task"""
    try:
        sync_manager.abort_sync_task(task_id)
        return {"success": True, "message": "Sync aborted"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/sync/history", response_class=HTMLResponse)
async def sync_history(request: Request):
    """Show sync history page"""
    sync_tasks = sync_manager.get_all_sync_tasks()
    active_task = sync_manager.get_active_sync_task()

    return templates.TemplateResponse(
        "sync_history.html",
        {"request": request, "sync_tasks": sync_tasks, "active_task": active_task},
    )
