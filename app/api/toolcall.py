"""OpenAI-style function calling (tool calls) support via the DSML protocol.

The Kimi web backend has no native function-calling API, so tool support is
implemented purely at the prompt level:

* **Request side** - when an OpenAI request carries a ``tools`` array, a system
  prompt describing the available tools (and the exact DSML output format) is
  injected, prior ``assistant`` tool calls are serialised back into DSML, and
  ``tool`` result messages are folded into ``user`` messages.
* **Response side** - the assistant text is scanned for a DSML
  ``<|DSML|tool_calls>`` block which is parsed back into OpenAI ``tool_calls``.
  For streaming responses a stateful :class:`ToolCallSieve` separates ordinary
  text deltas from the tool-call block in real time.

The DSML markup format and parsing approach are ported from the
``qing1189/qwen2026528`` reference project (``src/toolcall.js``).
"""

import json
import re
import secrets
from typing import Any, Dict, List, Optional, Tuple

TC_OPEN = "<|DSML|tool_calls>"
TC_CLOSE = "</|DSML|tool_calls>"

_INVOKE_RE = re.compile(
    r'<\|DSML\|invoke\s+name="([^"]+)"\s*>(.*?)</\|DSML\|invoke>',
    re.DOTALL,
)
_PARAM_RE = re.compile(
    r'<\|DSML\|parameter\s+name="([^"]+)"\s*>(.*?)</\|DSML\|parameter>',
    re.DOTALL,
)
_CDATA_RE = re.compile(r"^\s*<!\[CDATA\[(.*?)\]\]>\s*$", re.DOTALL)
_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")


# ---------------------------------------------------------------------------
# Tool detection
# ---------------------------------------------------------------------------

def _is_function_tool(tool: Any) -> bool:
    """Return True for OpenAI function tools (excludes built-ins like web_search)."""
    if not isinstance(tool, dict):
        return False
    tool_type = tool.get("type")
    if isinstance(tool_type, str) and tool_type.strip().lower() not in ("function", ""):
        return False
    return bool(tool.get("function") or tool.get("name"))


def _function_tools(tools: Optional[List[Any]]) -> List[Dict[str, Any]]:
    if not isinstance(tools, list):
        return []
    return [tool for tool in tools if _is_function_tool(tool)]


def has_tools(payload: Dict[str, Any]) -> bool:
    """Whether the request should be handled with DSML function calling.

    Requires at least one OpenAI function tool and ``tool_choice`` other than
    ``"none"``.
    """
    if not _function_tools(payload.get("tools")):
        return False

    tool_choice = payload.get("tool_choice")
    if isinstance(tool_choice, str) and tool_choice.strip().lower() == "none":
        return False
    return True


# ---------------------------------------------------------------------------
# Request side - prompt construction & message rewriting
# ---------------------------------------------------------------------------

def build_tool_prompt_block(tools: Optional[List[Any]]) -> str:
    """Build the system prompt that teaches the model the DSML call format."""
    tool_list = _function_tools(tools)

    decls: List[str] = []
    names: List[str] = []
    for tool in tool_list:
        fn = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        name = str(fn.get("name") or "").strip()
        if name:
            names.append(name)
        desc = str(fn.get("description") or "")
        params = fn.get("parameters")
        if params is None:
            params = fn.get("input_schema")
        params_block = "{}"
        if params is not None:
            try:
                params_block = json.dumps(params, ensure_ascii=False)
            except (TypeError, ValueError):
                params_block = "{}"
        decls.append(f"- {name}: {desc}\n  parameters: {params_block}")

    names_line = ", ".join(names) or "(none)"

    return "\n".join(
        [
            f"AVAILABLE TOOLS (all are real and callable): {names_line}",
            "",
            "When you decide to call a tool, output the call EXACTLY in this format:",
            "",
            TC_OPEN,
            '  <|DSML|invoke name="TOOL_NAME">',
            '    <|DSML|parameter name="ARG_NAME"><![CDATA[ARG_VALUE]]></|DSML|parameter>',
            "  </|DSML|invoke>",
            TC_CLOSE,
            "",
            "Rules:",
            f"1. Wrap one or more <|DSML|invoke> in a single {TC_OPEN} block.",
            "2. String parameters MUST use <![CDATA[...]]>.",
            "3. Numbers/booleans/null are plain text.",
            "4. Use only parameter names from the schemas below.",
            "5. Do NOT wrap in markdown fences. Do NOT explain after the block.",
            "6. If you call a tool, the block must be the last thing you output.",
            f"7. EVERY tool listed above ({names_line}) IS REAL and available. Do NOT refuse.",
            "",
            "Tools available:",
            "\n".join(decls),
        ]
    )


def serialize_assistant_tool_calls(tool_calls: Any) -> str:
    """Serialise OpenAI assistant ``tool_calls`` back into a DSML block."""
    if not isinstance(tool_calls, list) or not tool_calls:
        return ""

    blocks: List[str] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") if isinstance(call.get("function"), dict) else call
        name = str((fn or {}).get("name") or "").strip()
        if not name:
            continue
        args = (fn or {}).get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (ValueError, TypeError):
                pass
        blocks.append(_render_invoke(name, args))

    if not blocks:
        return ""
    return TC_OPEN + "\n" + "\n".join(blocks) + "\n" + TC_CLOSE


def serialize_tool_result(message: Dict[str, Any]) -> str:
    """Serialise an OpenAI ``tool`` role message into a DSML tool_result."""
    tool_id = message.get("tool_call_id") or ""
    content = message.get("content")
    if content is None:
        content = ""
    if not isinstance(content, str):
        try:
            content = json.dumps(content, ensure_ascii=False)
        except (TypeError, ValueError):
            content = str(content)
    return (
        f'<|DSML|tool_result tool_use_id="{_escape_attr(tool_id)}">'
        f"<![CDATA[{_escape_cdata(content)}]]></|DSML|tool_result>"
    )


def inject_tool_call_context(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Any]],
) -> List[Dict[str, Any]]:
    """Rewrite OpenAI messages so the Kimi backend can understand tool usage."""
    rewritten: List[Dict[str, Any]] = []
    for message in messages or []:
        if not isinstance(message, dict):
            rewritten.append(message)
            continue

        role = message.get("role")

        if (
            role == "assistant"
            and isinstance(message.get("tool_calls"), list)
            and message["tool_calls"]
        ):
            dsml = serialize_assistant_tool_calls(message["tool_calls"])
            base_text = message.get("content")
            base_text = base_text if isinstance(base_text, str) else ""
            merged = f"{base_text}\n{dsml}" if base_text else dsml
            out = {key: value for key, value in message.items() if key != "tool_calls"}
            out["content"] = merged
            rewritten.append(out)
            continue

        if role == "tool":
            rewritten.append({"role": "user", "content": serialize_tool_result(message)})
            continue

        rewritten.append(message)

    prompt_block = build_tool_prompt_block(tools)
    return [{"role": "system", "content": prompt_block}, *rewritten]


# ---------------------------------------------------------------------------
# Response side - non-streaming parsing
# ---------------------------------------------------------------------------

def parse_tool_calls_from_text(text: Optional[str]) -> Tuple[str, List[Dict[str, Any]]]:
    """Extract a trailing DSML tool-call block from assistant text.

    Returns a ``(content, tool_calls)`` tuple. When no valid block is present
    the original text is returned with an empty tool-call list.
    """
    if not text or not isinstance(text, str):
        return text or "", []

    last = _find_last_closed_block(text)
    if last is None:
        return text, []

    start, end = last
    calls = _parse_tool_calls_block(text[start:end])
    if not calls:
        return text, []

    content = re.sub(r"\s+$", "", text[:start])
    return content, calls


# ---------------------------------------------------------------------------
# Response side - streaming sieve
# ---------------------------------------------------------------------------

class ToolCallSieve:
    """Stateful filter that separates text deltas from a DSML tool-call block.

    Feed streamed content fragments through :meth:`push`; it returns the text
    that is safe to forward plus any completed tool-call deltas. Call
    :meth:`flush` once the upstream stream finishes to drain buffered text.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False
        self._block_buf = ""
        self._next_index = 0
        self._finished = False

    def push(self, chunk: str) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
        if self._finished:
            return "", None

        if not self._inside:
            self._buffer += chunk
            idx = self._buffer.find(TC_OPEN)
            if idx >= 0:
                before = self._buffer[:idx]
                self._block_buf = self._buffer[idx + len(TC_OPEN):]
                self._buffer = ""
                self._inside = True
                closed = self._flush_block()
                return before, closed

            # Hold back a partial TC_OPEN that may complete in the next chunk.
            for n in range(len(TC_OPEN) - 1, 0, -1):
                if self._buffer.endswith(TC_OPEN[:n]):
                    out = self._buffer[: len(self._buffer) - n]
                    self._buffer = self._buffer[len(self._buffer) - n:]
                    return out, None

            out = self._buffer
            self._buffer = ""
            return out, None

        self._block_buf += chunk
        return "", self._flush_block()

    def flush(self) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
        if self._finished:
            return "", None

        if not self._inside and self._buffer:
            out = self._buffer
            self._buffer = ""
            return out, None

        if self._inside and self._block_buf:
            wrapped = TC_OPEN + self._block_buf + TC_CLOSE
            calls = _parse_tool_calls_block(wrapped)
            if calls:
                self._finished = True
                self._inside = False
                self._block_buf = ""
                return "", self._as_deltas(calls)

            # Incomplete / invalid block - emit it verbatim as text.
            out = TC_OPEN + self._block_buf
            self._block_buf = ""
            self._inside = False
            return out, None

        return "", None

    def _flush_block(self) -> Optional[List[Dict[str, Any]]]:
        idx = self._block_buf.find(TC_CLOSE)
        if idx < 0:
            return None
        inner = self._block_buf[:idx]
        self._finished = True
        self._inside = False
        self._block_buf = ""
        calls = _parse_tool_calls_block(TC_OPEN + inner + TC_CLOSE)
        if not calls:
            return None
        return self._as_deltas(calls)

    def _as_deltas(self, calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deltas: List[Dict[str, Any]] = []
        for call in calls:
            deltas.append(
                {
                    "index": self._next_index,
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["function"]["name"],
                        "arguments": call["function"]["arguments"],
                    },
                }
            )
            self._next_index += 1
        return deltas


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_last_closed_block(text: str) -> Optional[Tuple[int, int]]:
    last_start, last_end, cursor = -1, -1, 0
    while True:
        start = text.find(TC_OPEN, cursor)
        if start < 0:
            break
        end = text.find(TC_CLOSE, start + len(TC_OPEN))
        if end < 0:
            break
        last_start = start
        last_end = end + len(TC_CLOSE)
        cursor = last_end
    if last_start < 0:
        return None
    return last_start, last_end


def _parse_tool_calls_block(block: str) -> List[Dict[str, Any]]:
    inner = block
    if inner.startswith(TC_OPEN):
        inner = inner[len(TC_OPEN):]
    if inner.endswith(TC_CLOSE):
        inner = inner[: -len(TC_CLOSE)]

    calls: List[Dict[str, Any]] = []
    for match in _INVOKE_RE.finditer(inner):
        name = match.group(1)
        params = _parse_parameters(match.group(2))
        calls.append(
            {
                "id": "call_" + secrets.token_hex(8),
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(params, ensure_ascii=False),
                },
            }
        )
    return calls


def _parse_parameters(body: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for match in _PARAM_RE.finditer(body):
        out[match.group(1)] = _decode_param_value(match.group(2))
    return out


def _decode_param_value(raw: str) -> Any:
    cdata = _CDATA_RE.match(raw)
    if cdata:
        value = cdata.group(1)
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value

    trimmed = raw.strip()
    if trimmed == "":
        return ""
    if _NUMBER_RE.match(trimmed):
        return float(trimmed) if "." in trimmed else int(trimmed)
    if trimmed == "true":
        return True
    if trimmed == "false":
        return False
    if trimmed == "null":
        return None
    return trimmed


def _render_invoke(name: str, args: Any) -> str:
    lines = [f'  <|DSML|invoke name="{_escape_attr(name)}">']
    if isinstance(args, dict):
        for key, value in args.items():
            lines.append("    " + _render_param(str(key), value))
    elif isinstance(args, str) and args:
        lines.append("    " + _render_param("content", args))
    lines.append("  </|DSML|invoke>")
    return "\n".join(lines)


def _render_param(name: str, value: Any) -> str:
    attr = _escape_attr(name)
    if value is None:
        return f'<|DSML|parameter name="{attr}"></|DSML|parameter>'
    if isinstance(value, str):
        return (
            f'<|DSML|parameter name="{attr}">'
            f"<![CDATA[{_escape_cdata(value)}]]></|DSML|parameter>"
        )
    if isinstance(value, bool):
        return f'<|DSML|parameter name="{attr}">{"true" if value else "false"}</|DSML|parameter>'
    if isinstance(value, (int, float)):
        return f'<|DSML|parameter name="{attr}">{value}</|DSML|parameter>'
    try:
        json_value = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        json_value = "{}"
    return (
        f'<|DSML|parameter name="{attr}">'
        f"<![CDATA[{_escape_cdata(json_value)}]]></|DSML|parameter>"
    )


def _escape_attr(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _escape_cdata(value: str) -> str:
    return str(value).replace("]]>", "]]]]><![CDATA[>")
