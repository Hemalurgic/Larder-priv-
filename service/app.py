"""FastAPI app serving the GraphQL API, judged cases and the test bench page (/testbench).

    LARDER_API_KEYS=key1,key2 uvicorn service.app:app --reload

Auth is a stub: keys come from LARDER_API_KEYS and are sent as `Authorization: Token <key>`
(or `Bearer <key>`, or `X-Api-Key: <key>`). With no keys configured every request is refused.
"""
from __future__ import annotations

import hmac
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from strawberry.fastapi import GraphQLRouter

from service.cases import router as cases_router
from service.library import library, rule_pack
from service.schema import schema

STATIC = Path(__file__).resolve().parent / "static"


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
app.include_router(GraphQLRouter(schema, graphql_ide=None), prefix="/graphql", dependencies=[Depends(require_key)])
app.include_router(cases_router, dependencies=[Depends(require_key)])


@app.get("/testbench", include_in_schema=False)
def testbench() -> FileResponse:
    """The test bench page. It holds no data; every call it makes sends the API key."""
    return FileResponse(STATIC / "testbench.html")


@app.get("/health")
def health() -> dict:
    recipes = [e.recipe for e in library().values()]
    return {"status": "ok", "rule_pack": rule_pack(), "recipes": len(recipes),
            "fixtures": sum(r.fixture for r in recipes), "with_images": sum(bool(r.image) for r in recipes)}
