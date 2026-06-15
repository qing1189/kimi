import time
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from ..kimi import Kimi2API

from .auth import verify_api_key
from .converters import (
    _apply_tool_calls,
    _chat_completion_to_dict,
    _chat_to_responses_api_dict,
    _extract_conversation_id,
    _normalize_messages,
    _response_api_to_chat_request,
)
from .errors import _json_error
from .models import (
    ModelResolutionError,
    _model_to_dict,
    _resolve_model,
    get_model_catalog,
)
from .streaming import (
    _create_streaming_chat_response,
    _create_streaming_responses_response,
)
from .toolcall import has_tools, inject_tool_call_context, _get_tool_choice_mode

router = APIRouter()


def _set_kimi_account(request: Request, account: Dict[str, str]) -> None:
    request.state.kimi_account_id = account.get("id", "")
    request.state.kimi_account_name = account.get("name", "")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/healthz")
async def healthz() -> Dict[str, Any]:
    """健康检查端点，返回服务状态和基本信息"""
    from ..core.kimi_account_pool import get_account_pool
    from ..dashboard.view_models import dashboard_stats

    # 基础健康状态
    health_info: Dict[str, Any] = {
        "status": "ok",
        "timestamp": time.time(),
    }

    # 账号池状态
    try:
        pool = get_account_pool(required=False)
        if pool:
            accounts_status = {
                "total": len(pool._accounts),
                "healthy": sum(1 for acc in pool._accounts if acc.selectable),
            }
            health_info["accounts"] = accounts_status
    except Exception:
        pass

    return health_info


@router.get("/readiness")
async def readiness() -> Dict[str, Any]:
    """就绪探针，检查服务是否准备好接收请求"""
    from ..core.kimi_account_pool import get_account_pool
    from ..config import Config

    ready = True
    checks: Dict[str, Any] = {}

    # 检查配置
    if not Config.ADMIN_PASSWORD:
        checks["admin_password"] = {"status": "warning", "message": "未配置管理密码"}
    else:
        checks["admin_password"] = {"status": "ok"}

    # 检查账号池
    try:
        pool = get_account_pool(required=False)
        if pool:
            healthy_count = sum(1 for acc in pool._accounts if acc.selectable)
            if healthy_count > 0:
                checks["accounts"] = {"status": "ok", "healthy": healthy_count}
            else:
                checks["accounts"] = {"status": "degraded", "message": "没有健康的账号"}
                ready = False
        else:
            checks["accounts"] = {"status": "not_configured"}
    except Exception as e:
        checks["accounts"] = {"status": "error", "message": str(e)}
        ready = False

    return {
        "ready": ready,
        "checks": checks,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@router.get("/v1/models", dependencies=[Depends(verify_api_key)])
async def list_models() -> Dict[str, Any]:
    now = int(time.time())
    catalog = await get_model_catalog()
    return {
        "object": "list",
        "data": [
            _model_to_dict(model, now)
            for model in catalog.models
        ],
    }


@router.get("/v1/models/{model_id}", dependencies=[Depends(verify_api_key)])
async def retrieve_model(model_id: str) -> Dict[str, Any]:
    now = int(time.time())
    catalog = await get_model_catalog()
    model = catalog.by_id(model_id)
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": f"Model `{model_id}` is not available",
                "type": "invalid_request_error",
            },
        )
    return _model_to_dict(model, now)


# ---------------------------------------------------------------------------
# Chat completions
# ---------------------------------------------------------------------------

@router.post(
    "/v1/chat/completions",
    dependencies=[Depends(verify_api_key)],
    response_model=None,
)
async def create_chat_completion(request: Request) -> Any:
    payload = await request.json()
    messages = _normalize_messages(payload.get("messages"))
    if not messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "`messages` is required", "type": "invalid_request_error"},
        )

    try:
        features = await _resolve_model(payload)
    except ModelResolutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc), "type": "invalid_request_error"},
        ) from exc
    request.state.request_model = features["request_model"]
    conversation_id = _extract_conversation_id(payload)
    stream = bool(payload.get("stream", False))

    tools_enabled = has_tools(payload)
    if tools_enabled:
        tool_choice = _get_tool_choice_mode(payload)
        messages = inject_tool_call_context(messages, payload.get("tools"), tool_choice)

    if stream:
        return StreamingResponse(
            _create_streaming_chat_response(
                request=request,
                model=features["model"],
                model_spec=features["model_spec"],
                response_model=features["request_model"],
                messages=messages,
                conversation_id=conversation_id,
                enable_web_search=features["enable_web_search"],
                tools_enabled=tools_enabled,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async with Kimi2API(on_account_used=lambda account: _set_kimi_account(request, account)) as client:
        result = await client.chat.completions.create(
            model=features["model"],
            model_spec=features["model_spec"],
            messages=messages,
            stream=False,
            conversation_id=conversation_id,
            enable_web_search=features["enable_web_search"],
        )
        result.model = features["request_model"]
        response = _chat_completion_to_dict(result)
        if tools_enabled:
            response = _apply_tool_calls(response)
        return response


# ---------------------------------------------------------------------------
# Completions (legacy)
# ---------------------------------------------------------------------------

@router.post("/v1/completions", dependencies=[Depends(verify_api_key)])
async def create_completion(request: Request) -> Dict[str, Any]:
    payload = await request.json()
    messages = _normalize_messages(prompt=payload.get("prompt"))
    if not messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "`prompt` is required", "type": "invalid_request_error"},
        )

    try:
        features = await _resolve_model(payload)
    except ModelResolutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc), "type": "invalid_request_error"},
        ) from exc
    request.state.request_model = features["request_model"]
    conversation_id = _extract_conversation_id(payload)

    async with Kimi2API(on_account_used=lambda account: _set_kimi_account(request, account)) as client:
        result = await client.chat.completions.create(
            model=features["model"],
            model_spec=features["model_spec"],
            messages=messages,
            conversation_id=conversation_id,
            enable_web_search=features["enable_web_search"],
        )
    result.model = features["request_model"]

    text = result.choices[0].message.content or ""
    return {
        "id": result.id,
        "object": "text_completion",
        "created": result.created,
        "model": result.model,
        "choices": [
            {
                "text": text,
                "index": 0,
                "logprobs": None,
                "finish_reason": result.choices[0].finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": result.usage.prompt_tokens,
            "completion_tokens": result.usage.completion_tokens,
            "total_tokens": result.usage.total_tokens,
        },
    }


# ---------------------------------------------------------------------------
# Responses API
# ---------------------------------------------------------------------------

@router.post(
    "/v1/responses",
    dependencies=[Depends(verify_api_key)],
    response_model=None,
)
async def create_response(request: Request) -> Any:
    payload = _response_api_to_chat_request(await request.json())
    messages = _normalize_messages(payload.get("messages"))
    if not messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "`input` or `messages` is required", "type": "invalid_request_error"},
        )

    try:
        features = await _resolve_model(payload)
    except ModelResolutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc), "type": "invalid_request_error"},
        ) from exc
    request.state.request_model = features["request_model"]
    conversation_id = _extract_conversation_id(payload)
    stream = bool(payload.get("stream", False))

    if stream:
        return StreamingResponse(
            _create_streaming_responses_response(
                request=request,
                model=features["model"],
                model_spec=features["model_spec"],
                response_model=features["request_model"],
                messages=messages,
                conversation_id=conversation_id,
                enable_web_search=features["enable_web_search"],
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async with Kimi2API(on_account_used=lambda account: _set_kimi_account(request, account)) as client:
        result = await client.chat.completions.create(
            model=features["model"],
            model_spec=features["model_spec"],
            messages=messages,
            stream=False,
            conversation_id=conversation_id,
            enable_web_search=features["enable_web_search"],
        )
        result.model = features["request_model"]
        return _chat_to_responses_api_dict(_chat_completion_to_dict(result))


# ---------------------------------------------------------------------------
# Unsupported endpoints catch-all
# ---------------------------------------------------------------------------

@router.api_route(
    "/v1/{unsupported_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    dependencies=[Depends(verify_api_key)],
)
async def unsupported_endpoint(unsupported_path: str) -> JSONResponse:
    return _json_error(
        f"Endpoint /v1/{unsupported_path} is not implemented for Kimi backend",
        "unsupported_endpoint",
        status.HTTP_501_NOT_IMPLEMENTED,
    )
