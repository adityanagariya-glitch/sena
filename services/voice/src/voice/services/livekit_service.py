from livekit import api

from voice.core.settings import settings


def generate_livekit_access(session_id: str, participant_name: str) -> dict:
    room = f"voice-case-note-{session_id}"
    grants = api.VideoGrants(room_join=True, room=room)
    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(participant_name)
        .with_name(participant_name)
        .with_grants(grants)
        .to_jwt()
    )
    return {"room_name": room, "token": token, "url": settings.livekit_url}
