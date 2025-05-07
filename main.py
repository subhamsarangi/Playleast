from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from youtube_analysis import get_or_analyze_playlist, extract_playlist_id, get_playlists

app = FastAPI()

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    playlists = get_playlists()
    return templates.TemplateResponse(
        "index.html", {"request": request, "playlists": playlists}
    )


@app.post("/analyze", response_class=HTMLResponse)
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
        return templates.TemplateResponse(
            "index.html", {"request": request, "error": str(e)}
        )


@app.get("/playlist/{playlist_id}", response_class=HTMLResponse)
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
        return templates.TemplateResponse(
            "index.html", {"request": request, "error": str(e)}
        )
