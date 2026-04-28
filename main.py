import os
import secrets
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.background import BackgroundTask

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
SECRET_TOKEN = os.getenv("SECRET_TOKEN")

if not SECRET_TOKEN:
    raise RuntimeError("SECRET_TOKEN environment variable is not set")

security = HTTPBearer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(base_url=OLLAMA_BASE_URL, timeout=None) as client:
        app.state.client = client
        yield


app = FastAPI(lifespan=lifespan)


async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not secrets.compare_digest(credentials.credentials, SECRET_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid token")


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"],
)
async def proxy_to_ollama(request: Request, path: str, _=Depends(verify_token)):
    url = httpx.URL(path=request.url.path, query=request.url.query.encode("utf-8"))

    body = await request.body()

    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("authorization", None)

    req = request.app.state.client.build_request(
        request.method,
        url,
        headers=headers,
        content=body,
    )

    r = await request.app.state.client.send(req, stream=True)

    response_headers = dict(r.headers)
    response_headers.pop("content-length", None)
    response_headers.pop("content-encoding", None)

    return StreamingResponse(
        r.aiter_bytes(),
        status_code=r.status_code,
        headers=response_headers,
        background=BackgroundTask(r.aclose),
    )
