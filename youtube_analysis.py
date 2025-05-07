import re
import datetime

import google_auth_oauthlib.flow
import googleapiclient.discovery
import isodate
import pandas as pd

from database import Playlist, Video, init_db, get_session


# Set up API client
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"
CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]

# Initialize database
db_engine = init_db()


def get_authenticated_service():
    """Get an authenticated YouTube API service instance."""
    flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, SCOPES
    )
    credentials = flow.run_local_server(port=8080)
    return googleapiclient.discovery.build(
        API_SERVICE_NAME, API_VERSION, credentials=credentials
    )


def extract_playlist_id(playlist_url):
    """Extract playlist ID from URL or return the ID if it's already extracted."""
    if playlist_url.startswith("http"):
        # Extract the playlist ID from the URL
        match = re.search(r"list=([a-zA-Z0-9_-]+)", playlist_url)
        if match:
            return match.group(1)
        else:
            raise ValueError("Could not extract playlist ID from URL")
    else:
        # Assuming the input is already a playlist ID
        return playlist_url


def get_playlist_info(youtube, playlist_id):
    """Get basic information about the playlist."""
    request = youtube.playlists().list(part="snippet,contentDetails", id=playlist_id)
    response = request.execute()

    if not response.get("items"):
        raise ValueError(f"Playlist with ID {playlist_id} not found")

    playlist_data = response["items"][0]

    return {
        "id": playlist_id,
        "title": playlist_data["snippet"]["title"],
        "channel_name": playlist_data["snippet"]["channelTitle"],
        "video_count": playlist_data["contentDetails"]["itemCount"],
        "url": f"https://www.youtube.com/playlist?list={playlist_id}",
    }


def get_playlist_videos(youtube, playlist_id):
    """Get all video IDs from a playlist."""
    video_ids = []
    next_page_token = None

    while True:
        request = youtube.playlistItems().list(
            part="contentDetails",
            maxResults=50,
            playlistId=playlist_id,
            pageToken=next_page_token,
        )
        response = request.execute()

        for item in response["items"]:
            video_ids.append(item["contentDetails"]["videoId"])

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    return video_ids


def get_video_details(youtube, video_ids):
    """Get details for a list of videos."""
    all_video_data = []

    # Process video IDs in chunks of 50 (API limitation)
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i : i + 50]

        request = youtube.videos().list(
            part="snippet,contentDetails,statistics", id=",".join(chunk)
        )
        response = request.execute()

        for item in response["items"]:
            video_data = {
                "id": item["id"],
                "title": item["snippet"]["title"],
                "duration": isodate.parse_duration(
                    item["contentDetails"]["duration"]
                ).total_seconds()
                / 60,  # in minutes
                "views": int(item.get("statistics", {}).get("viewCount", 0)),
                "likes": int(item.get("statistics", {}).get("likeCount", 0)),
            }

            # Calculate like percentage
            if video_data["views"] > 0:
                video_data["like_percentage"] = (
                    video_data["likes"] / video_data["views"]
                ) * 100
            else:
                video_data["like_percentage"] = 0

            # Create URL
            video_data["url"] = f"https://www.youtube.com/watch?v={video_data['id']}"

            all_video_data.append(video_data)

    return all_video_data


def get_or_analyze_playlist(playlist_id, force_refresh=False):
    """
    Check if playlist data exists in database, if not or if force_refresh is True,
    fetch and analyze playlist data.
    """
    try:
        session = get_session(db_engine)

        # Check if we have this playlist in the database and it's recent (less than 24 hours old)
        if not force_refresh:
            existing_playlist = (
                session.query(Playlist).filter(Playlist.id == playlist_id).first()
            )
            # Use data if it's less than 24 hours old
            if (
                existing_playlist
                and (
                    datetime.datetime.now() - existing_playlist.last_updated
                ).total_seconds()
                < 86400
            ):
                # Update the last_analyzed timestamp
                existing_playlist.last_analyzed = datetime.datetime.now()
                session.commit()
                # Return existing data from database
                all_videos = [
                    {
                        "title": video.title,
                        "duration": video.duration,
                        "views": video.views,
                        "likes": video.likes,
                        "like_percentage": video.like_percentage,
                        "url": video.url,
                    }
                    for video in existing_playlist.videos
                ]

                top_videos = [
                    {
                        "title": video.title,
                        "duration": video.duration,
                        "views": video.views,
                        "likes": video.likes,
                        "like_percentage": video.like_percentage,
                        "url": video.url,
                    }
                    for video in existing_playlist.videos
                    if video.is_top
                ]

                playlist_info = {
                    "id": existing_playlist.id,
                    "title": existing_playlist.title,
                    "channel_name": existing_playlist.channel_name,
                    "video_count": existing_playlist.video_count,
                    "url": existing_playlist.url,
                    "last_updated": existing_playlist.last_updated,
                    "last_analyzed": existing_playlist.last_analyzed,
                }

                session.close()
                return {
                    "playlist_info": playlist_info,
                    "top_videos": top_videos,
                    "all_videos": all_videos,
                    "from_cache": True,
                }

        # If force refresh or the data is older than 24hrs

        youtube = get_authenticated_service()
        playlist_info = get_playlist_info(youtube, playlist_id)
        video_ids = get_playlist_videos(youtube, playlist_id)
        video_data = get_video_details(youtube, video_ids)

        # Analyze data
        df = pd.DataFrame(video_data)
        TOP_N_PERCENT = 11 / 100

        if len(df) == 0:
            session.close()
            return {"error": "No videos found."}

        # Calculate normalized and rank data
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

        # Calculate top videos
        total_video_count = playlist_info["video_count"]
        if len(df_candidates) > 0:
            TOP_N_COUNT = len(df) * TOP_N_PERCENT
            if total_video_count > 5 and TOP_N_COUNT < 5:
                TOP_N_COUNT = total_video_count // 2
            else:
                TOP_N_COUNT = total_video_count - 2

            top_count = max(1, int(TOP_N_COUNT))
            top_threshold = df_candidates["combined_score"].nlargest(top_count).min()
            df["is_top"] = (
                (df["combined_score"] >= top_threshold)
                & df["above_median_views"]
                & df["above_median_likes"]
            )
        else:
            df["is_top"] = False

        # Save to database
        # First, check if playlist exists
        existing_playlist = (
            session.query(Playlist).filter(Playlist.id == playlist_id).first()
        )

        if existing_playlist:
            # Update existing playlist
            now = datetime.datetime.now()
            existing_playlist.title = playlist_info["title"]
            existing_playlist.channel_name = playlist_info["channel_name"]
            existing_playlist.video_count = playlist_info["video_count"]
            existing_playlist.last_updated = now
            existing_playlist.last_analyzed = now

            # Delete existing videos
            for video in existing_playlist.videos:
                session.delete(video)
        else:
            # Create new playlist
            now = datetime.datetime.now()
            new_playlist = Playlist(
                id=playlist_info["id"],
                title=playlist_info["title"],
                channel_name=playlist_info["channel_name"],
                video_count=playlist_info["video_count"],
                url=playlist_info["url"],
                last_updated=now,
                last_analyzed=now,
            )
            session.add(new_playlist)

        # Add all videos
        for _, row in df.iterrows():
            new_video = Video(
                id=row["id"],
                playlist_id=playlist_id,
                title=row["title"],
                duration=row["duration"],
                views=row["views"],
                likes=row["likes"],
                like_percentage=row["like_percentage"],
                url=row["url"],
                is_top=row["is_top"],
            )
            session.add(new_video)

        # Commit changes
        session.commit()

        # Return data
        top_videos = df[df["is_top"]][
            ["title", "duration", "views", "likes", "like_percentage", "url"]
        ].to_dict(orient="records")

        all_videos = df[
            ["title", "duration", "views", "likes", "like_percentage", "url"]
        ].to_dict(orient="records")

        # Add timestamps to playlist_info
        playlist_info.update({"last_updated": now, "last_analyzed": now})

        session.close()

        return {
            "playlist_info": playlist_info,
            "top_videos": top_videos,
            "all_videos": all_videos,
            "from_cache": False,
        }

    except Exception as e:
        # Make sure we close the session even if there's an error
        try:
            session.close()
        except:
            pass
        raise e


def get_playlists():
    try:
        session = get_session(db_engine)
        existing_playlists = (
            session.query(Playlist).order_by(Playlist.last_updated.desc()).all()
        )
        existing_playlist_info = []
        for playlist in existing_playlists:
            all_videos = [
                {
                    "title": video.title,
                    "duration": video.duration,
                    "views": video.views,
                    "likes": video.likes,
                    "like_percentage": video.like_percentage,
                    "url": video.url,
                    "is_top": video.is_top,
                }
                for video in playlist.videos
            ]

            existing_playlist_info.append(
                {
                    "id": playlist.id,
                    "title": playlist.title,
                    "channel_name": playlist.channel_name,
                    "all_video_count": playlist.video_count,
                    "url": playlist.url,
                    "last_updated": playlist.last_updated.strftime("%Y-%m-%d %H:%M"),
                    "last_analyzed": playlist.last_analyzed.strftime("%Y-%m-%d %H:%M"),
                    "all_videos": all_videos,
                }
            )

        return existing_playlist_info
    except Exception as e:
        try:
            session.close()
        except:
            pass
        raise e
