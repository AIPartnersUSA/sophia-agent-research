"""
Minimal token-mint service for local OSS LiveKit.

In LiveKit Cloud, room JWTs are issued by `lk cloud auth`. Self-hosting means
the operator (us) holds API_KEY + API_SECRET and mints JWTs ourselves. Client
code (web, Android, etc.) must NEVER hold the secret -- it calls this endpoint
to get a short-lived JWT it can hand to the SFU.

Run:
    uv run uvicorn token_mint:app --host 0.0.0.0 --port 8001 --reload

Usage from a client (browser/Android):
    POST http://localhost:8001/token
        { "identity": "user-123", "room": "sophia-room" }
    -> { "token": "eyJhbGc...", "url": "ws://localhost:7880" }
"""

import os
from datetime import timedelta
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from livekit import api
from pydantic import BaseModel

app = FastAPI(title="sophia-agent token-mint")

# CORS — open for local dev. In production, narrow to the specific origin(s)
# that should be allowed to mint tokens (e.g. https://sophia-app.vercel.app).
# Override via SOPHIA_CORS_ORIGINS env var as a comma-separated list.
_cors_env = os.environ.get("SOPHIA_CORS_ORIGINS", "*").strip()
_cors_origins = [o.strip() for o in _cors_env.split(",")] if _cors_env else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "ws://localhost:7880")
LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY", "devkey")
LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET", "devsecret-please-change")

# Shared API key for authenticating clients (browser, glasses) that want to
# mint a room token. In dev we leave this UNSET so the endpoint accepts any
# request — that matches today's behaviour. In production, set
# SOPHIA_TOKEN_API_KEY to a random 32+ character secret and configure
# clients to send it in the X-API-Key header. When the env var is unset or
# empty, the auth check is skipped entirely so dev runs continue working
# without code changes.
SOPHIA_TOKEN_API_KEY = os.environ.get("SOPHIA_TOKEN_API_KEY", "").strip()


DEFAULT_AGENT_NAME = "sophia-agent"


def _require_api_key(x_api_key: Optional[str]) -> None:
    """Reject if SOPHIA_TOKEN_API_KEY is configured AND the X-API-Key header
    is missing or wrong. No-op when the env var is unset (dev mode)."""
    if not SOPHIA_TOKEN_API_KEY:
        return
    if not x_api_key or x_api_key != SOPHIA_TOKEN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-API-Key header",
        )


class TokenRequest(BaseModel):
    identity: str
    room: str
    name: Optional[str] = None
    metadata: Optional[str] = None
    ttl_seconds: int = 3600
    # Agent dispatch. Default = sophia-agent (registered in agent.py via
    # @server.rtc_session(agent_name="sophia-agent")). Set to "" or null
    # explicitly to mint a token with NO agent dispatch (rare; only useful
    # for human-to-human-only rooms).
    agent_name: Optional[str] = DEFAULT_AGENT_NAME


class TokenResponse(BaseModel):
    token: str
    url: str
    identity: str
    room: str


@app.post("/token", response_model=TokenResponse)
def mint_token(
    req: TokenRequest,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> TokenResponse:
    _require_api_key(x_api_key)
    grants = api.VideoGrants(
        room_join=True,
        room=req.room,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
    )
    token = (
        api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(req.identity)
        .with_name(req.name or req.identity)
        .with_grants(grants)
        .with_ttl(timedelta(seconds=req.ttl_seconds))
    )
    if req.metadata:
        token = token.with_metadata(req.metadata)
    # Attach agent dispatch so the sophia-agent worker auto-joins this room
    # on first participant connect. Without this, a non-web client (like the
    # Unity glasses app) would land in an empty room with no agent. The web
    # frontend has its own token route that does the same thing.
    if req.agent_name:
        token = token.with_room_config(
            api.RoomConfiguration(
                agents=[api.RoomAgentDispatch(agent_name=req.agent_name)],
            )
        )
    return TokenResponse(
        token=token.to_jwt(),
        url=LIVEKIT_URL,
        identity=req.identity,
        room=req.room,
    )


@app.get("/health")
def health():
    return {"status": "ok", "livekit_url": LIVEKIT_URL}
