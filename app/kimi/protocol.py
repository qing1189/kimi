import base64
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

KIMI_CHAT_PATH = "/apiv2/kimi.gateway.chat.v1.ChatService/Chat"
KIMI_SUBSCRIPTION_PATH = (
    "/apiv2/kimi.gateway.order.v1.SubscriptionService/GetSubscription"
)
KIMI_RESEARCH_USAGE_PATH = "/api/chat/research/usage"
KIMI_SCENARIO = "SCENARIO_K2D5"

FAKE_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Origin": "https://www.kimi.com",
    "R-Timezone": "Asia/Shanghai",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Priority": "u=1, i",
    "X-Msh-Platform": "web",
}

THINKING_STAGE_NAME = "STAGE_NAME_THINKING"


class KimiAPIError(Exception):
    def __init__(
        self,
        message: str,
        *,
        retry_after: Optional[float] = None,
        upstream_status_code: int = 0,
        upstream_error_type: str = "",
    ):
        super().__init__(message)
        self.retry_after = retry_after
        self.upstream_status_code = int(upstream_status_code or 0)
        self.upstream_error_type = upstream_error_type


def generate_device_id() -> str:
    return str(random.randint(7000000000000000000, 7999999999999999999))


def generate_session_id() -> str:
    return str(random.randint(1700000000000000000, 1799999999999999999))


def parse_jwt(token: str) -> Optional[Dict[str, Any]]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")))
    except Exception:
        return None


def detect_token_type(token: str) -> str:
    if token.startswith("eyJ") and len(token.split(".")) == 3:
        payload = parse_jwt(token)
        if payload and payload.get("app_id") == "kimi" and payload.get("typ") == "access":
            return "jwt"
    return "refresh"


@dataclass
class Message:
    role: str
    content: Any
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None

    def text_content(self) -> str:
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            parts: List[str] = []
            for item in self.content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                    elif "text" in item:
                        parts.append(str(item.get("text", "")))
            return "\n".join(part for part in parts if part)
        if self.content is None:
            return ""
        return str(self.content)


@dataclass
class ChatCompletionMessage:
    role: str
    content: Optional[str]
    reasoning_content: Optional[str] = None


@dataclass
class ChatCompletionChoice:
    index: int
    message: ChatCompletionMessage
    finish_reason: str


@dataclass
class ChatCompletionUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class ChatCompletion:
    id: str
    created: int
    model: str
    choices: List[ChatCompletionChoice]
    usage: ChatCompletionUsage
    object: str = "chat.completion"


@dataclass
class ChatCompletionChunk:
    id: str
    created: int
    model: str
    choices: List[Dict[str, Any]]
    object: str = "chat.completion.chunk"


@dataclass
class ConversationContext:
    request_conversation_id: str
    remote_chat_id: Optional[str] = None
    last_assistant_message_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)


def _wrap_urls(text: str) -> str:
    return text


def _format_messages(messages: List[Message]) -> str:
    """Format messages into a single text payload for the Kimi backend.

    Tool calls and tool results are serialized using DSML format for
    consistency with the prompt-level tool calling approach. This ensures
    the model sees the same format in both injected context and history.
    """
    system_lines: List[str] = []
    body_lines: List[str] = []

    for message in messages:
        role = message.role
        text = message.text_content().strip()

        if role == "assistant" and message.tool_calls:
            # Serialize tool calls in DSML format for consistency with the
            # prompt-level tool calling approach. This way the model sees the
            # same DSML format in history as what it's expected to produce.
            from ..api.toolcall import serialize_assistant_tool_calls
            dsml_block = serialize_assistant_tool_calls(message.tool_calls)
            if dsml_block:
                text = f"{text}\n{dsml_block}" if text else dsml_block

        if role == "tool" and message.tool_call_id:
            # Convert tool results to DSML tool_result format
            from ..api.toolcall import serialize_tool_result, _escape_attr, _escape_cdata
            tool_id = message.tool_call_id or ""
            name = message.name or ""
            content = text
            name_attr = f' name="{_escape_attr(name)}"' if name else ""
            text = (
                f'<|DSML|tool_result tool_use_id="{_escape_attr(tool_id)}"{name_attr}>'
                f"<![CDATA[{_escape_cdata(content)}]]></|DSML|tool_result>"
            )
            role = "user"

        if not text:
            continue

        if role == "system":
            system_lines.append(text)
            continue

        if role == "user":
            text = _wrap_urls(text)

        body_lines.append(f"{role}:{text}")

    return "\n".join([*(f"system:{line}" for line in system_lines), *body_lines]).strip()


def _encode_connect_request(payload: Dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    header = bytearray(5)
    header[0] = 0x00
    header[1:5] = len(body).to_bytes(4, "big")
    return bytes(header) + body
