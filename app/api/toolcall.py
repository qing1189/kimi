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

Optimized implementation with:
- Chinese-optimized prompt engineering for higher compliance
- Robust parsing with multiple fallback strategies
- Improved streaming sieve with better partial block handling
- Support for tool_choice modes (auto, required, none)
- Comprehensive logging for debugging tool call failures
"""

import json
import logging
import re
import secrets
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("kimi2api.toolcall")

TC_OPEN = "<|DSML|tool_calls>"
TC_CLOSE = "</|DSML|tool_calls>"

# Primary DSML regex patterns
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

# Fallback JSON tool call patterns (for when model outputs JSON instead of DSML)
_JSON_TOOL_CALL_RE = re.compile(
    r'(?:```(?:json)?\s*)?\{\s*"(?:name|function)"\s*:\s*"([^"]+)"\s*,\s*'
    r'"(?:arguments|parameters|params)"\s*:\s*(\{[^}]*(?:\{[^}]*\}[^}]*)?\})\s*\}'
    r'(?:\s*```)?',
    re.DOTALL,
)

# Pattern for function_call style JSON: {"name": "fn", "arguments": {...}}
_FUNCTION_CALL_RE = re.compile(
    r'\{\s*"name"\s*:\s*"([^"]+)"\s*,\s*"arguments"\s*:\s*(\{.*?\})\s*\}',
    re.DOTALL,
)

# Pattern for tool_calls array style: [{"type": "function", "function": {"name": ..., "arguments": ...}}]
_TOOL_CALLS_ARRAY_RE = re.compile(
    r'\[\s*\{\s*"(?:type)"\s*:\s*"function"\s*,\s*"function"\s*:\s*'
    r'\{\s*"name"\s*:\s*"([^"]+)"\s*,\s*"arguments"\s*:\s*"?(.*?)"?\s*\}\s*\}\s*'
    r'(?:,\s*\{.*?\}\s*)*\]',
    re.DOTALL,
)

# Relaxed DSML patterns for slightly malformed outputs
_INVOKE_RELAXED_RE = re.compile(
    r'<\|?DSML\|?invoke\s+name\s*=\s*["\']([^"\']+)["\']\s*>(.*?)</\|?DSML\|?invoke>',
    re.DOTALL,
)
_PARAM_RELAXED_RE = re.compile(
    r'<\|?DSML\|?parameter\s+name\s*=\s*["\']([^"\']+)["\']\s*>(.*?)</\|?DSML\|?parameter>',
    re.DOTALL,
)

# Detect markdown-wrapped DSML blocks
_MARKDOWN_DSML_RE = re.compile(
    r'```(?:xml|dsml|tool)?\s*\n?(.*?)\n?\s*```',
    re.DOTALL,
)


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


def _get_tool_choice_mode(payload: Dict[str, Any]) -> str:
    """Extract the tool_choice mode: 'auto', 'required', or a specific function name."""
    tool_choice = payload.get("tool_choice")
    if tool_choice is None:
        return "auto"
    if isinstance(tool_choice, str):
        return tool_choice.strip().lower()
    if isinstance(tool_choice, dict):
        # {"type": "function", "function": {"name": "specific_fn"}}
        fn = tool_choice.get("function", {})
        if isinstance(fn, dict) and fn.get("name"):
            return f"function:{fn['name']}"
    return "auto"


# ---------------------------------------------------------------------------
# Request side - prompt construction & message rewriting
# ---------------------------------------------------------------------------

def build_tool_prompt_block(tools: Optional[List[Any]], tool_choice: str = "auto") -> str:
    """Build the system prompt that teaches the model the DSML call format.

    Optimized for maximum compliance:
    - Detailed bilingual instructions for broader compatibility
    - Multiple examples including correct and incorrect patterns
    - Strong constraint language with consequences
    - Explicit format templates
    """
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
        decls.append(f"### {name}\n- Description: {desc}\n- Parameters: {params_block}")

    names_line = ", ".join(names) or "(none)"

    # Build tool choice instruction
    choice_instruction = ""
    if tool_choice == "required":
        choice_instruction = (
            "\n\n⚠️ CRITICAL: You MUST call at least one tool in your response. "
            "Do NOT respond with only text. Always include a tool call block.\n"
            "⚠️ 关键要求：你必须调用至少一个工具。不要只回复文本，必须包含工具调用块。\n"
        )
    elif tool_choice.startswith("function:"):
        fn_name = tool_choice[len("function:"):]
        choice_instruction = (
            f"\n\n⚠️ CRITICAL: You MUST call the function `{fn_name}` in your response.\n"
            f"⚠️ 关键要求：你必须在回复中调用函数 `{fn_name}`。\n"
        )

    return "\n".join(
        [
            "# TOOL CALLING INSTRUCTIONS / 工具调用指令",
            "# 你必须严格遵守以下格式，否则工具调用会失败！",
            "",
            f"You have access to these tools: {names_line}",
            f"你可以使用以下工具：{names_line}",
            "",
            "## MANDATORY FORMAT / 必须使用的格式",
            "",
            "When you need to call a tool, you MUST output EXACTLY this format:",
            "当你需要调用工具时，必须严格按照以下格式输出：",
            "",
            "```",
            TC_OPEN,
            '  <|DSML|invoke name="tool_name">',
            '    <|DSML|parameter name="param1"><![CDATA[string_value]]></|DSML|parameter>',
            '    <|DSML|parameter name="param2">123</|DSML|parameter>',
            '    <|DSML|parameter name="param3">true</|DSML|parameter>',
            "  </|DSML|invoke>",
            TC_CLOSE,
            "```",
            "",
            "## STRICT RULES / 严格规则（违反会导致调用失败）",
            "",
            "1. ✅ The tool call block MUST be the LAST thing in your response.",
            "   ✅ 工具调用块必须是你回复的最后内容。",
            "",
            "2. ✅ String values MUST use <![CDATA[...]]> wrapper.",
            "   ✅ 字符串值必须用 <![CDATA[...]]> 包裹。",
            "",
            "3. ✅ Numbers and booleans (true/false) are plain text, no quotes.",
            "   ✅ 数字和布尔值直接写，不要加引号。",
            "",
            "4. ❌ Do NOT wrap in markdown code blocks (no ``` around the tool call).",
            "   ❌ 不要用 markdown 代码块包裹工具调用。",
            "",
            "5. ❌ Do NOT output JSON format. Only DSML format works!",
            "   ❌ 不要输出 JSON 格式，只有 DSML 格式有效！",
            "",
            "6. ❌ Do NOT add any text after the closing tag.",
            "   ❌ 不要在关闭标签后添加任何文字。",
            "",
            "7. ✅ You may call multiple tools using multiple <|DSML|invoke> blocks.",
            "   ✅ 可以用多个 <|DSML|invoke> 调用多个工具。",
            "",
            "## CORRECT EXAMPLE / 正确示例",
            "",
            "User: What's the weather in Beijing?",
            "User: 北京天气怎么样？",
            "",
            "Assistant: Let me check the weather for you.",
            "Assistant: 我来帮你查一下天气。",
            "",
            TC_OPEN,
            '  <|DSML|invoke name="get_weather">',
            '    <|DSML|parameter name="city"><![CDATA[Beijing]]></|DSML|parameter>',
            '    <|DSML|parameter name="days">3</|DSML|parameter>',
            "  </|DSML|invoke>",
            TC_CLOSE,
            "",
            "## WRONG EXAMPLES / 错误示例（不要这样做！）",
            "",
            "❌ WRONG 1: Using JSON format (this will fail!):",
            '```json',
            '{"name": "get_weather", "arguments": {"city": "Beijing"}}',
            "```",
            "",
            "❌ WRONG 2: Adding text after closing tag:",
            TC_OPEN,
            '  <|DSML|invoke name="get_weather">',
            '    <|DSML|parameter name="city"><![CDATA[Beijing]]></|DSML|parameter>',
            "  </|DSML|invoke>",
            TC_CLOSE,
            "Hope this helps! (WRONG - no text after closing tag!)",
            "",
            "❌ WRONG 3: Using markdown wrapper:",
            "```",
            TC_OPEN,
            '  <|DSML|invoke name="get_weather">',
            '    <|DSML|parameter name="city"><![CDATA[Beijing]]></|DSML|parameter>',
            "  </|DSML|invoke>",
            TC_CLOSE,
            "```",
            "",
            choice_instruction,
            "## AVAILABLE TOOLS / 可用工具",
            "",
            "\n\n".join(decls),
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
    """Serialise an OpenAI ``tool`` role message into a DSML tool_result block.

    Enhanced format provides clearer context for the model to understand
    tool results and continue the conversation properly.
    """
    tool_id = message.get("tool_call_id") or ""
    name = message.get("name") or ""
    content = message.get("content")
    if content is None:
        content = ""
    if not isinstance(content, str):
        try:
            content = json.dumps(content, ensure_ascii=False)
        except (TypeError, ValueError):
            content = str(content)

    # Include function name if available for better context
    name_attr = f' name="{_escape_attr(name)}"' if name else ""
    return (
        f'<|DSML|tool_result tool_use_id="{_escape_attr(tool_id)}"{name_attr}>'
        f"<![CDATA[{_escape_cdata(content)}]]></|DSML|tool_result>"
    )


def _build_tool_result_context(results: List[str]) -> str:
    """Wrap tool results with context explanation for the model."""
    header = "以下是工具调用的结果，请根据这些结果继续回复用户："
    return header + "\n" + "\n".join(results)


def inject_tool_call_context(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Any]],
    tool_choice: str = "auto",
) -> List[Dict[str, Any]]:
    """Rewrite OpenAI messages so the Kimi backend can understand tool usage.

    Enhanced to:
    - Support tool_choice modes
    - Better handle consecutive tool messages
    - Preserve context for multi-turn tool conversations
    """
    rewritten: List[Dict[str, Any]] = []
    pending_tool_results: List[str] = []

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
            # Flush any pending tool results before the assistant message
            if pending_tool_results:
                rewritten.append({"role": "user", "content": "\n".join(pending_tool_results)})
                pending_tool_results = []

            dsml = serialize_assistant_tool_calls(message["tool_calls"])
            base_text = message.get("content")
            base_text = base_text if isinstance(base_text, str) else ""
            merged = f"{base_text}\n{dsml}" if base_text else dsml
            out = {key: value for key, value in message.items() if key != "tool_calls"}
            out["content"] = merged
            rewritten.append(out)
            continue

        if role == "tool":
            # Collect consecutive tool results to batch them together
            pending_tool_results.append(serialize_tool_result(message))
            continue

        # Flush pending tool results before any non-tool message
        if pending_tool_results:
            rewritten.append({"role": "user", "content": _build_tool_result_context(pending_tool_results)})
            pending_tool_results = []

        rewritten.append(message)

    # Flush remaining tool results
    if pending_tool_results:
        rewritten.append({"role": "user", "content": _build_tool_result_context(pending_tool_results)})

    prompt_block = build_tool_prompt_block(tools, tool_choice)
    return [{"role": "system", "content": prompt_block}, *rewritten]


# ---------------------------------------------------------------------------
# Response side - non-streaming parsing
# ---------------------------------------------------------------------------

def parse_tool_calls_from_text(text: Optional[str]) -> Tuple[str, List[Dict[str, Any]]]:
    """Extract a trailing DSML tool-call block from assistant text.

    Returns a ``(content, tool_calls)`` tuple. Enhanced to try multiple
    parsing strategies:
    1. Standard DSML block detection
    2. Markdown-wrapped DSML block detection
    3. Relaxed DSML parsing for slightly malformed output
    4. Fallback JSON tool call detection (multiple patterns)

    When no valid block is present the original text is returned with an
    empty tool-call list.
    """
    if not text or not isinstance(text, str):
        return text or "", []

    # Strategy 1: Standard DSML block
    last = _find_last_closed_block(text)
    if last is not None:
        start, end = last
        calls = _parse_tool_calls_block(text[start:end])
        if calls:
            content = re.sub(r"\s+$", "", text[:start])
            logger.debug("Tool calls parsed via standard DSML block: %s", [c["function"]["name"] for c in calls])
            return content, calls

    # Strategy 2: Check for markdown-wrapped DSML block
    calls = _try_parse_markdown_wrapped(text)
    if calls is not None:
        content_text, tool_calls = calls
        logger.debug("Tool calls parsed via markdown-wrapped DSML: %s", [c["function"]["name"] for c in tool_calls])
        return content_text, tool_calls

    # Strategy 3: Try unclosed DSML block (model forgot closing tag)
    calls = _try_parse_unclosed_block(text)
    if calls is not None:
        content_text, tool_calls = calls
        logger.debug("Tool calls parsed via unclosed DSML block: %s", [c["function"]["name"] for c in tool_calls])
        return content_text, tool_calls

    # Strategy 4: Fallback JSON tool call detection
    calls = _try_parse_json_tool_calls(text)
    if calls is not None:
        content_text, tool_calls = calls
        logger.debug("Tool calls parsed via JSON fallback: %s", [c["function"]["name"] for c in tool_calls])
        return content_text, tool_calls

    logger.debug("No tool calls detected in response text (length=%d)", len(text))
    return text, []


# ---------------------------------------------------------------------------
# Response side - streaming sieve
# ---------------------------------------------------------------------------

class ToolCallSieve:
    """Stateful filter that separates text deltas from a DSML tool-call block.

    Feed streamed content fragments through :meth:`push`; it returns the text
    that is safe to forward plus any completed tool-call deltas. Call
    :meth:`flush` once the upstream stream finishes to drain buffered text.

    Enhanced with:
    - Better partial marker detection (holds back more aggressively)
    - Fallback JSON detection on flush
    - Handling of markdown-wrapped blocks
    """

    # Characters that might indicate start of tool call markers
    _HOLD_CHARS = frozenset("<{[`")

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False
        self._block_buf = ""
        self._next_index = 0
        self._finished = False
        self._total_content = ""  # Track all content for fallback parsing

    def push(self, chunk: str) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
        if self._finished:
            return "", None

        self._total_content += chunk

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

            # Also check for markdown-wrapped DSML opening
            md_idx = self._buffer.find("```")
            if md_idx >= 0 and TC_OPEN in self._buffer[md_idx:]:
                tc_idx = self._buffer.find(TC_OPEN, md_idx)
                before = self._buffer[:md_idx]
                self._block_buf = self._buffer[tc_idx + len(TC_OPEN):]
                self._buffer = ""
                self._inside = True
                closed = self._flush_block()
                return before, closed

            # Hold back partial TC_OPEN that may complete in the next chunk
            hold_len = self._compute_hold_length()
            if hold_len > 0:
                out = self._buffer[: len(self._buffer) - hold_len]
                self._buffer = self._buffer[len(self._buffer) - hold_len:]
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
            # Try fallback parsing on the complete content
            calls = self._try_fallback_parse()
            if calls:
                # Remove tool call portion from output
                content, _ = parse_tool_calls_from_text(self._total_content)
                self._finished = True
                return "", self._as_deltas(calls)
            return out, None

        if self._inside and self._block_buf:
            # Try to parse what we have (model may have forgotten closing tag)
            wrapped = TC_OPEN + self._block_buf + TC_CLOSE
            calls = _parse_tool_calls_block(wrapped)
            if calls:
                self._finished = True
                self._inside = False
                self._block_buf = ""
                return "", self._as_deltas(calls)

            # Try relaxed parsing on the buffer content
            calls = _parse_tool_calls_relaxed(self._block_buf)
            if calls:
                self._finished = True
                self._inside = False
                self._block_buf = ""
                return "", self._as_deltas(calls)

            # Incomplete / invalid block - emit it verbatim as text
            out = TC_OPEN + self._block_buf
            self._block_buf = ""
            self._inside = False
            return out, None

        # Final fallback: check if the complete content has tool calls
        calls = self._try_fallback_parse()
        if calls:
            self._finished = True
            return "", self._as_deltas(calls)

        return "", None

    def _compute_hold_length(self) -> int:
        """Compute how many trailing bytes to hold back for potential markers."""
        # Check for partial TC_OPEN
        for n in range(len(TC_OPEN) - 1, 0, -1):
            if self._buffer.endswith(TC_OPEN[:n]):
                return n

        # Check for potential JSON tool call start patterns
        # Hold back if we end with characters that could start a tool call
        if self._buffer.endswith("<"):
            return 1
        if self._buffer.endswith("<|"):
            return 2
        if self._buffer.endswith("<|D"):
            return 3
        if self._buffer.endswith("<|DS"):
            return 4

        return 0

    def _flush_block(self) -> Optional[List[Dict[str, Any]]]:
        idx = self._block_buf.find(TC_CLOSE)
        if idx < 0:
            # Also check for markdown closing that contains TC_CLOSE
            md_close = self._block_buf.find("```")
            if md_close >= 0:
                # Check if there's a TC_CLOSE before the markdown close
                inner_close = self._block_buf.find(TC_CLOSE[:len(TC_CLOSE)], 0, md_close)
                if inner_close >= 0:
                    idx = inner_close
            if idx < 0:
                return None

        inner = self._block_buf[:idx]
        self._finished = True
        self._inside = False
        self._block_buf = ""
        calls = _parse_tool_calls_block(TC_OPEN + inner + TC_CLOSE)
        if not calls:
            # Try relaxed parsing
            calls = _parse_tool_calls_relaxed(inner)
        if not calls:
            return None
        return self._as_deltas(calls)

    def _try_fallback_parse(self) -> Optional[List[Dict[str, Any]]]:
        """Try fallback parsing strategies on complete content."""
        if not self._total_content:
            return None

        # Try JSON fallback
        result = _try_parse_json_tool_calls(self._total_content)
        if result is not None:
            _, calls = result
            return calls

        return None

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
# Internal helpers - DSML parsing
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


def _parse_tool_calls_relaxed(text: str) -> List[Dict[str, Any]]:
    """Parse tool calls using relaxed regex patterns for slightly malformed output."""
    calls: List[Dict[str, Any]] = []
    for match in _INVOKE_RELAXED_RE.finditer(text):
        name = match.group(1)
        params = _parse_parameters_relaxed(match.group(2))
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


def _parse_parameters_relaxed(body: str) -> Dict[str, Any]:
    """Parse parameters with relaxed regex."""
    out: Dict[str, Any] = {}
    for match in _PARAM_RELAXED_RE.finditer(body):
        out[match.group(1)] = _decode_param_value(match.group(2))
    if not out:
        # Fallback: try standard regex
        for match in _PARAM_RE.finditer(body):
            out[match.group(1)] = _decode_param_value(match.group(2))
    return out


def _decode_param_value(raw: str) -> Any:
    cdata = _CDATA_RE.match(raw)
    if cdata:
        value = cdata.group(1)
        # Try to parse as JSON first (for objects, arrays, numbers, booleans)
        try:
            parsed = json.loads(value)
            return parsed
        except (ValueError, TypeError):
            return value

    trimmed = raw.strip()
    if trimmed == "":
        return ""
    if _NUMBER_RE.match(trimmed):
        return float(trimmed) if "." in trimmed else int(trimmed)
    if trimmed.lower() == "true":
        return True
    if trimmed.lower() == "false":
        return False
    if trimmed.lower() == "null" or trimmed.lower() == "none":
        return None

    # Try parsing as JSON (model may have put raw JSON without CDATA)
    if trimmed.startswith("{") or trimmed.startswith("[") or trimmed.startswith('"'):
        try:
            return json.loads(trimmed)
        except (ValueError, TypeError):
            pass

    return trimmed


# ---------------------------------------------------------------------------
# Internal helpers - fallback parsers
# ---------------------------------------------------------------------------

def _try_parse_markdown_wrapped(text: str) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
    """Try to extract DSML blocks wrapped in markdown code fences."""
    for md_match in _MARKDOWN_DSML_RE.finditer(text):
        inner = md_match.group(1)
        if TC_OPEN in inner:
            # Extract the DSML block from within the markdown
            tc_start = inner.find(TC_OPEN)
            tc_end = inner.find(TC_CLOSE)
            if tc_end > tc_start:
                block = inner[tc_start:tc_end + len(TC_CLOSE)]
                calls = _parse_tool_calls_block(block)
                if calls:
                    content = re.sub(r"\s+$", "", text[:md_match.start()])
                    return content, calls
    return None


def _try_parse_unclosed_block(text: str) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
    """Try to parse an unclosed DSML block (model forgot closing tag)."""
    idx = text.find(TC_OPEN)
    if idx < 0:
        return None

    # Take everything after TC_OPEN as the block content
    inner = text[idx + len(TC_OPEN):]

    # Check if there are valid invoke blocks even without closing tag
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

    if not calls:
        # Try relaxed parsing
        for match in _INVOKE_RELAXED_RE.finditer(inner):
            name = match.group(1)
            params = _parse_parameters_relaxed(match.group(2))
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

    if calls:
        content = re.sub(r"\s+$", "", text[:idx])
        return content, calls

    return None


def _try_parse_json_tool_calls(text: str) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
    """Try to detect and parse JSON-formatted tool calls as a fallback.

    Some models may output tool calls in JSON format instead of DSML when
    the prompt isn't followed perfectly. This catches common patterns like:

    1. {"name": "fn", "arguments": {...}}
    2. [{"type": "function", "function": {"name": "fn", "arguments": "..."}}]
    3. ```json\n{"name": "fn", "parameters": {...}}\n```
    4. function_call: {"name": "fn", "arguments": {...}}
    """
    # Look for JSON tool call patterns at the end of the text
    # Only trigger if the text doesn't already have DSML markers
    if TC_OPEN in text:
        return None

    # Strategy 1: Try to find a JSON block at the end (possibly in markdown)
    json_block_match = re.search(
        r'(?:```(?:json)?\s*\n?)(\[?\s*\{.*?\}\s*\]?)(?:\s*\n?```)?$',
        text,
        re.DOTALL,
    )

    if json_block_match:
        json_text = json_block_match.group(1).strip()
        calls = _parse_json_as_tool_calls(json_text)
        if calls:
            content = re.sub(r"\s+$", "", text[:json_block_match.start()])
            return content, calls

    # Strategy 2: Look for "function_call:" or "tool_calls:" prefix
    prefix_match = re.search(
        r'(?:function_call|tool_calls?)\s*:\s*(\{.*?\}|\[.*?\])\s*$',
        text,
        re.DOTALL,
    )
    if prefix_match:
        json_text = prefix_match.group(1).strip()
        calls = _parse_json_as_tool_calls(json_text)
        if calls:
            content = re.sub(r"\s+$", "", text[:prefix_match.start()])
            return content, calls

    # Strategy 3: Try without markdown fences - look for a JSON object/array at the end
    # that looks like a tool call
    trailing_json_match = re.search(
        r'(\{[^{}]*"(?:name|function)"[^{}]*"(?:arguments|parameters|params)"[^{}]*\{.*?\}[^{}]*\})\s*$',
        text,
        re.DOTALL,
    )
    if trailing_json_match:
        json_text = trailing_json_match.group(1).strip()
        calls = _parse_json_as_tool_calls(json_text)
        if calls:
            content = re.sub(r"\s+$", "", text[:trailing_json_match.start()])
            return content, calls

    # Strategy 4: Look for OpenAI-style function_call in message
    openai_match = re.search(
        r'"function_call"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]+)"[^}]*"arguments"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}',
        text,
    )
    if openai_match:
        name = openai_match.group(1)
        args_str = openai_match.group(2).replace('\\"', '"').replace('\\\\', '\\')
        try:
            json.loads(args_str)  # Validate JSON
            calls = [{
                "id": "call_" + secrets.token_hex(8),
                "type": "function",
                "function": {"name": name, "arguments": args_str},
            }]
            content = re.sub(r"\s+$", "", text[:openai_match.start()])
            return content, calls
        except (ValueError, TypeError):
            pass

    return None


def _parse_json_as_tool_calls(json_text: str) -> List[Dict[str, Any]]:
    """Try to parse a JSON string as tool calls."""
    calls: List[Dict[str, Any]] = []

    try:
        data = json.loads(json_text)
    except (ValueError, TypeError):
        # Try fixing common JSON issues
        try:
            # Remove trailing commas
            fixed = re.sub(r',\s*([}\]])', r'\1', json_text)
            data = json.loads(fixed)
        except (ValueError, TypeError):
            return []

    if isinstance(data, dict):
        # Single tool call: {"name": "fn", "arguments": {...}}
        call = _extract_single_json_call(data)
        if call:
            calls.append(call)
    elif isinstance(data, list):
        # Array of tool calls
        for item in data:
            if isinstance(item, dict):
                call = _extract_single_json_call(item)
                if call:
                    calls.append(call)

    return calls


def _extract_single_json_call(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract a tool call from a single JSON object."""
    name = None
    arguments = None

    # Pattern 1: {"name": "fn", "arguments": {...}}
    if "name" in data and ("arguments" in data or "parameters" in data or "params" in data):
        name = str(data["name"])
        arguments = data.get("arguments") or data.get("parameters") or data.get("params") or {}

    # Pattern 2: {"function": {"name": "fn", "arguments": "..."}, "type": "function"}
    elif "function" in data and isinstance(data["function"], dict):
        fn = data["function"]
        name = str(fn.get("name", ""))
        arguments = fn.get("arguments") or fn.get("parameters") or {}

    if not name:
        return None

    # Normalize arguments to JSON string
    if isinstance(arguments, str):
        # Verify it's valid JSON
        try:
            json.loads(arguments)
            args_str = arguments
        except (ValueError, TypeError):
            args_str = json.dumps({"value": arguments}, ensure_ascii=False)
    elif isinstance(arguments, dict):
        args_str = json.dumps(arguments, ensure_ascii=False)
    else:
        args_str = "{}"

    return {
        "id": "call_" + secrets.token_hex(8),
        "type": "function",
        "function": {
            "name": name,
            "arguments": args_str,
        },
    }


# ---------------------------------------------------------------------------
# Internal helpers - rendering
# ---------------------------------------------------------------------------

def _render_invoke(name: str, args: Any) -> str:
    lines = [f'  <|DSML|invoke name="{_escape_attr(name)}">']
    if isinstance(args, dict):
        for key, value in args.items():
            lines.append("    " + _render_param(str(key), value))
    elif isinstance(args, str) and args:
        # Try to parse as JSON first
        try:
            parsed = json.loads(args)
            if isinstance(parsed, dict):
                for key, value in parsed.items():
                    lines.append("    " + _render_param(str(key), value))
            else:
                lines.append("    " + _render_param("content", args))
        except (ValueError, TypeError):
            lines.append("    " + _render_param("content", args))
    lines.append("  </|DSML|invoke>")
    return "\n".join(lines)


def _render_param(name: str, value: Any) -> str:
    attr = _escape_attr(name)
    if value is None:
        return f'<|DSML|parameter name="{attr}">null</|DSML|parameter>'
    if isinstance(value, str):
        return (
            f'<|DSML|parameter name="{attr}">'
            f"<![CDATA[{_escape_cdata(value)}]]></|DSML|parameter>"
        )
    if isinstance(value, bool):
        return f'<|DSML|parameter name="{attr}">{"true" if value else "false"}</|DSML|parameter>'
    if isinstance(value, (int, float)):
        return f'<|DSML|parameter name="{attr}">{value}</|DSML|parameter>'
    # For complex types (dict, list), serialize as JSON in CDATA
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
