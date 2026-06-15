import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import Request

from ..kimi import Kimi2API, KimiAPIError, ChatCompletionChunk
from ..kimi.model_catalog import KimiModelSpec
from .toolcall import ToolCallSieve

logger = logging.getLogger("kimi2api.api")


def _stream_error_chunk(message: str, error_type: str = "api_error") -> str:
    payload = {
        "error": {
            "message": message,
            "type": error_type,
            "param": None,
            "code": error_type,
        }
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _mark_stream_error(
    request: Optional[Request],
    message: str = "",
    exc: Optional[KimiAPIError] = None,
) -> None:
    if request is not None:
        request.state.stream_error = True
        request.state.stream_error_message = message
        if exc is not None:
            request.state.upstream_status_code = exc.upstream_status_code
            request.state.upstream_error_type = exc.upstream_error_type
            request.state.upstream_retry_after = exc.retry_after or 0.0


def _mark_kimi_account(request: Optional[Request], account: Dict[str, str]) -> None:
    if request is not None:
        request.state.kimi_account_id = account.get("id", "")
        request.state.kimi_account_name = account.get("name", "")


async def _stream_chat_chunks(
    stream: AsyncIterator[ChatCompletionChunk],
    response_model: str,
    tools_enabled: bool = False,
) -> AsyncIterator[str]:
    sieve = ToolCallSieve() if tools_enabled else None
    tool_calls_emitted = False
    content_emitted = False

    async for chunk in stream:
        if sieve is None:
            yield _chat_chunk_sse(chunk, response_model, chunk.choices)
            continue

        choice = chunk.choices[0] if chunk.choices else {}
        delta = choice.get("delta", {})
        finish_reason = choice.get("finish_reason")

        if delta.get("content"):
            text_delta, tool_calls_delta = sieve.push(delta["content"])
            if text_delta:
                content_emitted = True
                yield _chat_chunk_sse(
                    chunk,
                    response_model,
                    [{"index": 0, "delta": {"content": text_delta}, "finish_reason": None}],
                )
            if tool_calls_delta:
                tool_calls_emitted = True
                yield _chat_chunk_sse(
                    chunk,
                    response_model,
                    [
                        {
                            "index": 0,
                            "delta": {"tool_calls": tool_calls_delta},
                            "finish_reason": None,
                        }
                    ],
                )
            continue

        if finish_reason is not None:
            text_delta, tool_calls_delta = sieve.flush()
            if text_delta:
                content_emitted = True
                yield _chat_chunk_sse(
                    chunk,
                    response_model,
                    [{"index": 0, "delta": {"content": text_delta}, "finish_reason": None}],
                )
            if tool_calls_delta:
                tool_calls_emitted = True
                yield _chat_chunk_sse(
                    chunk,
                    response_model,
                    [
                        {
                            "index": 0,
                            "delta": {"tool_calls": tool_calls_delta},
                            "finish_reason": None,
                        }
                    ],
                )
            final_reason = "tool_calls" if tool_calls_emitted else finish_reason
            yield _chat_chunk_sse(
                chunk,
                response_model,
                [{"index": 0, "delta": {}, "finish_reason": final_reason}],
            )
            continue

        yield _chat_chunk_sse(chunk, response_model, chunk.choices)
    yield "data: [DONE]\n\n"


def _chat_chunk_sse(
    chunk: ChatCompletionChunk,
    response_model: str,
    choices: List[Dict[str, Any]],
) -> str:
    payload = {
        "id": chunk.id,
        "object": chunk.object,
        "created": chunk.created,
        "model": response_model,
        "choices": choices,
        "system_fingerprint": "fp_kimi2api",
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _stream_responses_chunks(
    stream: AsyncIterator[ChatCompletionChunk],
) -> AsyncIterator[str]:
    async for chunk in stream:
        delta = chunk.choices[0].get("delta", {})
        event: Dict[str, Any] = {
            "type": "response.output_text.delta",
            "sequence_number": 0,
            "item_id": f"msg_{chunk.id}",
            "output_index": 0,
            "content_index": 0,
            "delta": delta.get("content", ""),
        }

        if delta.get("reasoning_content"):
            event = {
                "type": "response.reasoning.delta",
                "sequence_number": 0,
                "item_id": f"msg_{chunk.id}",
                "output_index": 0,
                "content_index": 0,
                "delta": delta["reasoning_content"],
            }
        elif delta.get("role"):
            continue
        elif chunk.choices[0].get("finish_reason"):
            event = {"type": "response.completed", "response": {"id": chunk.id}}

        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


async def _create_streaming_chat_response(
    *,
    request: Optional[Request] = None,
    model: str,
    model_spec: KimiModelSpec,
    response_model: str,
    messages: List[Dict[str, Any]],
    conversation_id: Optional[str],
    enable_web_search: bool,
    tools_enabled: bool = False,
) -> AsyncIterator[str]:
    client: Optional[Kimi2API] = None
    try:
        client = Kimi2API(on_account_used=lambda account: _mark_kimi_account(request, account))
        stream = await client.chat.completions.create(
            model=model,
            model_spec=model_spec,
            messages=messages,
            stream=True,
            conversation_id=conversation_id,
            enable_web_search=enable_web_search,
        )
        async for chunk in _stream_chat_chunks(stream, response_model, tools_enabled):
            yield chunk
    except KimiAPIError as exc:
        _mark_stream_error(request, str(exc), exc)
        logger.warning("Streaming chat request failed: %s", exc)
        yield _stream_error_chunk(str(exc))
        yield "data: [DONE]\n\n"
    except Exception:
        _mark_stream_error(request, "Streaming request failed")
        logger.exception("Unexpected streaming chat request failure")
        yield _stream_error_chunk("Streaming request failed")
        yield "data: [DONE]\n\n"
    finally:
        if client is not None:
            await client.close()


async def _create_streaming_responses_response(
    *,
    request: Optional[Request] = None,
    model: str,
    model_spec: KimiModelSpec,
    response_model: str,
    messages: List[Dict[str, Any]],
    conversation_id: Optional[str],
    enable_web_search: bool,
) -> AsyncIterator[str]:
    client: Optional[Kimi2API] = None
    try:
        client = Kimi2API(on_account_used=lambda account: _mark_kimi_account(request, account))
        stream = await client.chat.completions.create(
            model=model,
            model_spec=model_spec,
            messages=messages,
            stream=True,
            conversation_id=conversation_id,
            enable_web_search=enable_web_search,
        )
        async for chunk in _stream_responses_chunks(stream):
            yield chunk
    except KimiAPIError as exc:
        _mark_stream_error(request, str(exc), exc)
        logger.warning("Streaming responses request failed: %s", exc)
        yield _stream_error_chunk(str(exc))
        yield "data: [DONE]\n\n"
    except Exception:
        _mark_stream_error(request, "Streaming request failed")
        logger.exception("Unexpected streaming responses request failure")
        yield _stream_error_chunk("Streaming request failed")
        yield "data: [DONE]\n\n"
    finally:
        if client is not None:
            await client.close()
