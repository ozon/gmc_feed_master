from __future__ import annotations

import json
import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..access import CurrentUser, get_current_user
from ..ai.service import AiChatUnavailable
from ..chat import SYSTEM_PROMPT, TOOL_SCHEMAS, execute_tool
from ..db.engine import get_db_session

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=50)


def _ai_service(request: Request):
    service = getattr(request.app.state, "ai_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="ai service unavailable")
    return service


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db_session: Annotated[AsyncSession | None, Depends(get_db_session)],
) -> dict[str, Any]:
    if payload.messages[-1].role != "user":
        raise HTTPException(status_code=422, detail="last message must be from the user")
    if db_session is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    service = _ai_service(request)
    client_id = (
        next(iter(user.client_ids))
        if user.client_ids is not None and len(user.client_ids) == 1
        else None
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [m.model_dump() for m in payload.messages]
    try:
        for _round in range(MAX_TOOL_ROUNDS):
            response = await service.complete_chat(
                messages, TOOL_SCHEMAS, client_id=client_id
            )
            if not response.tool_calls:
                return {"content": response.content}
            messages.append({
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": response.tool_calls,
            })
            for call in response.tool_calls:
                fn = call.get("function") or {}
                try:
                    arguments = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {"error": "invalid arguments JSON"}
                result = await execute_tool(
                    db_session, user, str(fn.get("name", "")), arguments
                )
                messages.append({
                    "role": "tool",
                    "content": json.dumps(result, default=str),
                    "tool_call_id": str(call.get("id", "")),
                })
        raise HTTPException(status_code=502, detail="tool_loop_exhausted")
    except AiChatUnavailable as exc:
        raise HTTPException(
            status_code=503, detail=f"ai unavailable: {exc.error_code}"
        ) from exc
