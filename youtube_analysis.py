import re
import google_auth_oauthlib.flow
import googleapiclient.discovery
import isodate

# Set up API client
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"
CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]


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
                "title": item["snippet"]["title"],
                "video_id": item["id"],
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
            video_data["url"] = (
                f"https://www.youtube.com/watch?v={video_data['video_id']}"
            )

            all_video_data.append(video_data)

    return all_video_data
