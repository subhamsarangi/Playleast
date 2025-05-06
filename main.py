from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from youtube_analysis import (
    extract_playlist_id,
    get_authenticated_service,
    get_playlist_videos,
    get_video_details,
)
import pandas as pd

app = FastAPI()

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

TOP_N_PERCENT = 7 / 100


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/analyze", response_class=HTMLResponse)
def analyze(request: Request, playlist_url: str = Form(...)):
    try:
        playlist_id = extract_playlist_id(playlist_url)
        youtube = get_authenticated_service()
        video_ids = get_playlist_videos(youtube, playlist_id)
        video_data = get_video_details(youtube, video_ids)

        df = pd.DataFrame(video_data)
        if len(df) == 0:
            return templates.TemplateResponse(
                "index.html", {"request": request, "error": "No videos found."}
            )

        df["views_normalized"] = (
            df["views"] / df["views"].max() if df["views"].max() > 0 else 0
        )
        df["like_percentage_normalized"] = df["like_percentage"] / 100
        df["views_rank"] = df["views"].rank(pct=True)
        df["likes_rank"] = df["like_percentage"].rank(pct=True)
        df["above_median_views"] = df["views_rank"] >= 0.5
        df["above_median_likes"] = df["likes_rank"] >= 0.5
        df["combined_score"] = df["views_normalized"] * df["like_percentage_normalized"]
        df_candidates = df[df["above_median_views"] & df["above_median_likes"]]

        if len(df_candidates) > 0:
            top_count = max(1, int(len(df) * TOP_N_PERCENT))
            top_threshold = df_candidates["combined_score"].nlargest(top_count).min()
            df["is_top"] = (
                (df["combined_score"] >= top_threshold)
                & df["above_median_views"]
                & df["above_median_likes"]
            )
        else:
            df["is_top"] = False

        # Separate datasets
        top_videos = df[df["is_top"]][
            ["title", "duration", "views", "likes", "like_percentage", "url"]
        ].to_dict(orient="records")

        all_videos = df[
            ["title", "duration", "views", "likes", "like_percentage", "url"]
        ].to_dict(orient="records")

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "top_videos": top_videos,
                "all_videos": all_videos,
                "playlist_url": playlist_url,
            },
        )

    except Exception as e:
        return templates.TemplateResponse(
            "index.html", {"request": request, "error": str(e)}
        )
