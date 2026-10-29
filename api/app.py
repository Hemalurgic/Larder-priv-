"""FastAPI app serving the GraphQL API.

    LARDER_API_KEYS=key1,key2 uvicorn api.app:app --reload

Auth is a stub: keys come from LARDER_API_KEYS and are sent as `Authorization: Token <key>`
(or `Bearer <key>`, or `X-Api-Key: <key>`). With no keys configured every request is refused.
"""
from __future__ import annotations

import hmac
import os

from fastapi import Depends, FastAPI, HTTPException, Request
from strawberry.fastapi import GraphQLRouter

from api.library import library, rule_pack
from api.schema import schema


def _keys() -> list[str]:
    return [k.strip() for k in os.environ.get("LARDER_API_KEYS", "").split(",") if k.strip()]


def require_key(request: Request) -> None:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() not in ("token", "bearer"):
        token = request.headers.get("x-api-key", "")
    if not token or not any(hmac.compare_digest(token, k) for k in _keys()):
        raise HTTPException(status_code=401, detail="Missing or unknown API key. "
                                                    "Send it as `Authorization: Token <key>`.")


app = FastAPI(title="Larder", version="0.1.0")
app.include_router(GraphQLRouter(schema), prefix="/graphql", dependencies=[Depends(require_key)])


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "rule_pack": rule_pack(), "recipes": len(library())}
