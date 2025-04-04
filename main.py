from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.security.api_key import APIKeyHeader
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from typing import List, Optional
import os
import asyncio
import random
import httpx
import logging
from contextlib import asynccontextmanager

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Keep track of the ping task
ping_task = None

# Create a startup event to start the ping task
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the ping task
    global ping_task
    ping_task = asyncio.create_task(keep_alive())

    yield

    # Cancel the ping task on shutdown
    if ping_task:
        ping_task.cancel()
        try:
            await ping_task
        except asyncio.CancelledError:
            logger.info("Ping task cancelled")

# Initialize FastAPI app
app = FastAPI(
    title="YouTube Data API",
    description="API to fetch YouTube titles, thumbnails, and transcriptions",
    lifespan=lifespan
)

# Self-ping function to keep the instance alive
async def keep_alive():
    # Get the app URL from environment variable or use a default for local development
    app_url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:8000")
    health_endpoint = f"{app_url}/health"

    while True:
        try:
            # Randomize the interval between 7 and 12 minutes (420-720 seconds)
            interval = random.randint(420, 720)
            logger.info(f"Next ping in {interval} seconds")

            # Wait for the interval
            await asyncio.sleep(interval)

            # Ping the health endpoint
            async with httpx.AsyncClient() as client:
                response = await client.get(health_endpoint)
                logger.info(f"Ping status: {response.status_code}")

        except Exception as e:
            logger.error(f"Error in keep-alive ping: {str(e)}")
            # Even if we encounter an error, wait before trying again
            await asyncio.sleep(300)  # 5 minutes

# API Security setup
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

# YouTube API setup
YOUTUBE_API_KEY = os.environ.get('YOUTUBE_API_KEY', 'your-api-key-here')

# Authorization dependency
async def get_api_key(api_key: str = Depends(api_key_header)):
    if api_key != os.environ.get("API_KEY", "your-api-key-here"):
        raise HTTPException(status_code=403, detail="Could not validate API key")
    return api_key

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "Service is running"}


@app.get("/get_title")
async def get_title(
    video_id: str = Query(..., description="YouTube Video ID"),
    api_key: str = Depends(get_api_key)
):
    """
    Fetch the title of a YouTube video by its ID.
    """
    try:
        youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
        response = youtube.videos().list(
            part='snippet',
            id=video_id
        ).execute()

        if not response['items']:
            raise HTTPException(status_code=404, detail="Video not found")

        title = response['items'][0]['snippet']['title']
        return {"title": title}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_thumbnail")
async def get_thumbnail(
    video_id: str = Query(..., description="YouTube Video ID"),
    api_key: str = Depends(get_api_key)
):
    """
    Fetch the thumbnails of a YouTube video by its ID.
    """
    try:
        youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
        response = youtube.videos().list(
            part='snippet',
            id=video_id
        ).execute()

        if not response['items']:
            raise HTTPException(status_code=404, detail="Video not found")

        thumbnails = response['items'][0]['snippet']['thumbnails']
        return {"thumbnails": thumbnails}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get_transcript")
async def get_transcript(
    video_id: str = Query(..., description="YouTube Video ID"),
    languages: Optional[List[str]] = Query(["en"], description="List of language codes in priority order"),
    preserve_formatting: bool = Query(False, description="Preserve HTML formatting elements"),
    api_key: str = Depends(get_api_key)
):
    """
    Fetch the transcript of a YouTube video by its ID.
    """
    try:
        ytt_api = YouTubeTranscriptApi()
        fetched_transcript = ytt_api.fetch(
            video_id, 
            languages=languages,
            preserve_formatting=preserve_formatting
        )

        # Convert to simplified JSON response
        response = {
            "transcript": fetched_transcript.to_raw_data(),
            "video_id": fetched_transcript.video_id,
            "language": fetched_transcript.language,
            "language_code": fetched_transcript.language_code,
            "is_generated": fetched_transcript.is_generated
        }

        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/list_transcripts")
async def list_transcripts(
    video_id: str = Query(..., description="YouTube Video ID"),
    api_key: str = Depends(get_api_key)
):
    """
    List all available transcripts for a YouTube video.
    """
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.list(video_id)

        transcripts = []
        for transcript in transcript_list:
            transcripts.append({
                "video_id": transcript.video_id,
                "language": transcript.language,
                "language_code": transcript.language_code,
                "is_generated": transcript.is_generated,
                "is_translatable": transcript.is_translatable,
                "translation_languages": [
                    {"language": lang.language, "language_code": lang.language_code}
                    for lang in transcript.translation_languages
                ]
            })

        return {"transcripts": transcripts}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/translate_transcript")
async def translate_transcript(
    video_id: str = Query(..., description="YouTube Video ID"),
    source_languages: Optional[List[str]] = Query(["en"], description="List of source language codes in priority order"),
    target_language: str = Query(..., description="Target language code"),
    api_key: str = Depends(get_api_key)
):
    """
    Translate the transcript of a YouTube video to a target language.
    """
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.list(video_id)

        # Find the transcript in one of the source languages
        transcript = transcript_list.find_transcript(source_languages)

        # Translate the transcript
        translated_transcript = transcript.translate(target_language)
        fetched_transcript = translated_transcript.fetch()

        # Convert to simplified JSON response
        response = {
            "transcript": fetched_transcript.to_raw_data(),
            "video_id": fetched_transcript.video_id,
            "language": fetched_transcript.language,
            "language_code": fetched_transcript.language_code,
            "is_generated": fetched_transcript.is_generated
        }

        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)