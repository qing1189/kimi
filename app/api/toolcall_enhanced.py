"""Enhanced Tool Call implementation inspired by ds2api's Tool Sieve.

This module provides an improved tool call parsing and streaming system with:
1. Advanced state machine for leak-free streaming
2. Better partial marker detection and buffering
3. Robust XML normalization and repair mechanisms
4. Support for fullwidth DSML prefix variants
5. Code fence protection to avoid intercepting examples
"""

import json
import logging
import re
import secrets
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("kimi2api.toolcall_enhanced")

# DSML markers
TC_OPEN = "<|DSML|tool_calls>"
TC_CLOSE = "</|DSML|tool_calls>"

# Alternative DSML formats
DSML_VARIANTS = [
    ("<|DSML|tool_calls>", "</|DSML|tool_calls>"),
    ("<dsml-tool-calls>", "</dsml-tool-calls>"),
    ("<tool_calls>", "</tool_calls>"),
]

# Fullwidth variant (some models may output this)
FULLWIDTH_DSML_OPEN = "＜｜ＤＳＭＬ｜tool_calls＞"
FULLWIDTH_DSML_CLOSE = "＜／｜ＤＳＭＬ｜tool_calls＞"


class SieveState(Enum):
    """Tool sieve state machine states."""
    TEXT = "text"  # Emitting normal text
    CAPTURING = "capturing"  # Capturing tool call block
    FINISHED = "finished"  # Tool calls parsed, done


# ---------------------------------------------------------------------------
# XML Normalization - inspired by ds2api's normalizeDSMLToolCallMarkup
# ---------------------------------------------------------------------------

def normalize_dsml_markup(text: str) -> str:
    """Normalize various DSML markup formats to canonical XML.

    Handles:
    - DSML shell: <|DSML|tool_calls>
    - Hyphenated: <dsml-tool-calls>
    - Legacy canonical: <tool_calls>
    - Fullwidth variants: ＜｜ＤＳＭＬ｜tool_calls＞
    - Typo tolerance: repeated prefixes, trailing pipes
    """
    # Normalize fullwidth to halfwidth first
    result = _normalize_fullwidth_dsml(text)

    # Apply patterns iteratively until no more changes
    # This handles nested/repeated patterns
    max_iterations = 10
    for _ in range(max_iterations):
        before = result

        # Closing tags - pattern is </|DSML|tag>
        result = re.sub(r'<\s*/\s*\|*\s*DSML\s*\|+\s*tool_calls\s*\|*\s*>', '</tool_calls>', result, flags=re.IGNORECASE)
        result = re.sub(r'<\s*/\s*\|*\s*DSML\s*\|+\s*invoke\s*\|*\s*>', '</invoke>', result, flags=re.IGNORECASE)
        result = re.sub(r'<\s*/\s*\|*\s*DSML\s*\|+\s*parameter\s*\|*\s*>', '</parameter>', result, flags=re.IGNORECASE)
        result = re.sub(r'<\s*/\s*\|*\s*DSML\s*\|+\s*tool_result\s*\|*\s*>', '</tool_result>', result, flags=re.IGNORECASE)

        # Opening tags - pattern is <|DSML|tag>
        result = re.sub(r'<+\s*\|*\s*DSML\s*\|+\s*tool_calls\s*\|*\s*>', '<tool_calls>', result, flags=re.IGNORECASE)
        result = re.sub(r'<+\s*\|*\s*DSML\s*\|+\s*invoke\s+', '<invoke ', result, flags=re.IGNORECASE)
        result = re.sub(r'<+\s*\|*\s*DSML\s*\|+\s*parameter\s+', '<parameter ', result, flags=re.IGNORECASE)
        result = re.sub(r'<+\s*\|*\s*DSML\s*\|+\s*tool_result\s+', '<tool_result ', result, flags=re.IGNORECASE)

        # Hyphenated variants
        result = re.sub(r'</dsml-tool-calls>', '</tool_calls>', result, flags=re.IGNORECASE)
        result = re.sub(r'</dsml-invoke>', '</invoke>', result, flags=re.IGNORECASE)
        result = re.sub(r'</dsml-parameter>', '</parameter>', result, flags=re.IGNORECASE)
        result = re.sub(r'<dsml-tool-calls>', '<tool_calls>', result, flags=re.IGNORECASE)
        result = re.sub(r'<dsml-invoke\s+', '<invoke ', result, flags=re.IGNORECASE)
        result = re.sub(r'<dsml-parameter\s+', '<parameter ', result, flags=re.IGNORECASE)

        # No more changes, we're done
        if result == before:
            break

    return result


def _normalize_fullwidth_dsml(text: str) -> str:
    """Convert fullwidth DSML markers to halfwidth."""
    replacements = [
        (FULLWIDTH_DSML_OPEN, TC_OPEN),
        (FULLWIDTH_DSML_CLOSE, TC_CLOSE),
        ('＜｜ＤＳＭＬ｜invoke', '<|DSML|invoke'),
        ('＜／｜ＤＳＭＬ｜invoke＞', '</|DSML|invoke>'),
        ('＜｜ＤＳＭＬ｜parameter', '<|DSML|parameter'),
        ('＜／｜ＤＳＭＬ｜parameter＞', '</|DSML|parameter>'),
    ]

    result = text
    for fw, hw in replacements:
        result = result.replace(fw, hw)

    return result


# ---------------------------------------------------------------------------
# Code Fence Detection - prevent intercepting examples
# ---------------------------------------------------------------------------

def is_inside_code_fence(text: str, position: int) -> bool:
    """Check if a position in text is inside a markdown code fence.

    Prevents intercepting tool call examples in code blocks.
    """
    before = text[:position]

    # Count code fence markers before this position
    fence_count = before.count("```")

    # Odd number means we're inside a code fence
    return fence_count % 2 == 1


def find_tool_markup_outside_fences(text: str, marker: str) -> int:
    """Find marker position that's not inside a code fence."""
    pos = 0
    while True:
        idx = text.find(marker, pos)
        if idx < 0:
            return -1

        if not is_inside_code_fence(text, idx):
            return idx

        pos = idx + 1

    return -1


# ---------------------------------------------------------------------------
# Partial Marker Detection
# ---------------------------------------------------------------------------

def find_partial_tool_tag_start(text: str) -> int:
    """Find the start position of a partial tool markup tag at the end.

    Returns the index where the partial tag starts, or -1 if none found.
    This prevents emitting incomplete markers like "<|DSM" as text.
    """
    if not text:
        return -1

    # Check for partial matches of known opening markers
    markers_to_check = [
        TC_OPEN,  # <|DSML|tool_calls>
        "<dsml-tool-calls>",
        "<tool_calls>",
        "```",  # Code fence
    ]

    for marker in markers_to_check:
        # Check all possible partial matches (from longest to shortest)
        for length in range(min(len(marker), len(text)), 0, -1):
            partial = marker[:length]
            if text.endswith(partial):
                return len(text) - length

    return -1


def split_safe_content(text: str) -> Tuple[str, str]:
    """Split text into safe-to-emit content and held-back partial marker.

    Returns (safe_content, held_back).
    """
    partial_start = find_partial_tool_tag_start(text)

    if partial_start >= 0:
        return text[:partial_start], text[partial_start:]

    return text, ""


# ---------------------------------------------------------------------------
# XML Repair Mechanisms
# ---------------------------------------------------------------------------

def sanitize_loose_cdata(text: str) -> str:
    """Close unclosed CDATA sections to prevent parse failures.

    If a <![CDATA[ is opened but not closed, this adds ]]> to allow parsing.
    """
    # Find all CDATA openings and closings
    cdata_open_count = text.count("<![CDATA[")
    cdata_close_count = text.count("]]>")

    if cdata_open_count > cdata_close_count:
        # Add missing closing markers
        missing = cdata_open_count - cdata_close_count
        text += "]]>" * missing

    return text


def repair_missing_wrapper(block: str) -> str:
    """Repair missing opening <tool_calls> wrapper.

    If block contains <invoke> and </tool_calls> but no opening <tool_calls>,
    add the missing opening tag.
    """
    normalized = normalize_dsml_markup(block)

    # Check if we have invoke tags but missing opening wrapper
    has_invoke = '<invoke' in normalized
    has_close_wrapper = '</tool_calls>' in normalized
    has_open_wrapper = '<tool_calls>' in normalized

    if has_invoke and has_close_wrapper and not has_open_wrapper:
        # Find where to insert the opening tag
        invoke_pos = normalized.find('<invoke')
        if invoke_pos > 0:
            # Add opening before first invoke
            return normalized[:invoke_pos] + '<tool_calls>\n' + normalized[invoke_pos:]
        else:
            return '<tool_calls>\n' + normalized

    return normalized


# ---------------------------------------------------------------------------
# Enhanced Tool Call Sieve - inspired by ds2api's state machine
# ---------------------------------------------------------------------------

class EnhancedToolCallSieve:
    """Advanced stateful filter for separating text from tool calls.

    Improvements over basic sieve:
    1. Better partial marker detection (holds back more aggressively)
    2. Code fence awareness (ignores tool calls in examples)
    3. XML normalization before parsing
    4. Repair mechanisms for common model errors
    5. Fallback strategies for various formats
    """

    def __init__(self) -> None:
        self.state = SieveState.TEXT
        self.pending = ""  # Buffer for text being processed
        self.capture = ""  # Buffer for captured tool call block
        self.total_content = ""  # Full content for fallback parsing
        self.next_index = 0

    def push(self, chunk: str) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
        """Process a new chunk from the stream.

        Returns (text_to_emit, tool_calls_or_none).
        """
        if self.state == SieveState.FINISHED:
            return "", None

        self.total_content += chunk

        if self.state == SieveState.TEXT:
            return self._process_text_state(chunk)
        else:  # CAPTURING
            return self._process_capturing_state(chunk)

    def flush(self) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
        """Flush remaining buffers at end of stream."""
        if self.state == SieveState.FINISHED:
            return "", None

        if self.state == SieveState.TEXT:
            # Try fallback parsing on complete content
            text, calls = self._try_fallback_parse(self.total_content)
            if calls:
                self.state = SieveState.FINISHED
                return "", self._as_deltas(calls)

            out = self.pending
            self.pending = ""
            return out, None

        # CAPTURING state - try to parse what we have
        if self.capture:
            # Apply normalization and repair
            normalized = normalize_dsml_markup(self.capture)
            repaired = repair_missing_wrapper(normalized)
            sanitized = sanitize_loose_cdata(repaired)

            # Wrap in markers if not already present
            if not sanitized.startswith('<tool_calls>'):
                sanitized = '<tool_calls>\n' + sanitized
            if not sanitized.endswith('</tool_calls>'):
                sanitized = sanitized + '\n</tool_calls>'

            calls = self._parse_xml_block(sanitized)
            if calls:
                self.state = SieveState.FINISHED
                return "", self._as_deltas(calls)

            # Failed to parse - emit as text
            out = TC_OPEN + self.capture
            self.capture = ""
            return out, None

        return "", None

    def _process_text_state(self, chunk: str) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
        """Process chunk in TEXT state."""
        self.pending += chunk

        # Look for tool call opening marker (outside code fences)
        idx = find_tool_markup_outside_fences(self.pending, TC_OPEN)

        if idx >= 0:
            # Found opening marker - switch to CAPTURING
            before = self.pending[:idx]
            self.capture = self.pending[idx + len(TC_OPEN):]
            self.pending = ""
            self.state = SieveState.CAPTURING

            # Check if already closed
            return before, self._try_consume_capture()

        # Check for alternative DSML markers
        for open_marker, _ in DSML_VARIANTS[1:]:  # Skip first (already checked)
            idx = find_tool_markup_outside_fences(self.pending, open_marker)
            if idx >= 0:
                before = self.pending[:idx]
                self.capture = self.pending[idx + len(open_marker):]
                self.pending = ""
                self.state = SieveState.CAPTURING
                return before, self._try_consume_capture()

        # No marker found - split safe vs partial
        safe, held = split_safe_content(self.pending)
        self.pending = held
        return safe, None

    def _process_capturing_state(self, chunk: str) -> Tuple[str, Optional[List[Dict[str, Any]]]]:
        """Process chunk in CAPTURING state."""
        self.capture += chunk
        return "", self._try_consume_capture()

    def _try_consume_capture(self) -> Optional[List[Dict[str, Any]]]:
        """Try to consume and parse the captured block."""
        # Look for closing marker
        close_idx = -1
        close_marker_len = 0

        # Try all known closing markers
        for open_m, close_m in DSML_VARIANTS:
            idx = self.capture.find(close_m)
            if idx >= 0:
                close_idx = idx
                close_marker_len = len(close_m)
                break

        if close_idx < 0:
            # Not closed yet
            return None

        # Extract the inner content (before closing marker)
        inner = self.capture[:close_idx]

        # Build full block with canonical markers
        block = f"<tool_calls>\n{inner}\n</tool_calls>"

        # Apply normalization and repair
        normalized = normalize_dsml_markup(block)
        repaired = repair_missing_wrapper(normalized)
        sanitized = sanitize_loose_cdata(repaired)

        # Parse
        calls = self._parse_xml_block(sanitized)

        if calls:
            self.state = SieveState.FINISHED
            self.capture = ""
            return self._as_deltas(calls)

        # Failed to parse - continue capturing
        return None

    def _parse_xml_block(self, block: str) -> List[Dict[str, Any]]:
        """Parse a normalized XML tool call block."""
        from . import toolcall as legacy

        # Use the existing robust parser from the original implementation
        try:
            calls = legacy._parse_tool_calls_block(block)
            if calls:
                return calls

            # Try relaxed parsing
            calls = legacy._parse_tool_calls_relaxed(block)
            return calls or []
        except Exception as e:
            logger.warning(f"XML parsing failed: {e}")
            return []

    def _try_fallback_parse(self, text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Try fallback parsing strategies on complete content."""
        from . import toolcall as legacy

        # Use the comprehensive fallback parsers from original implementation
        return legacy.parse_tool_calls_from_text(text)

    def _as_deltas(self, calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert tool calls to delta format for streaming."""
        deltas: List[Dict[str, Any]] = []
        for call in calls:
            deltas.append({
                "index": self.next_index,
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["function"]["name"],
                    "arguments": call["function"]["arguments"],
                },
            })
            self.next_index += 1
        return deltas


# ---------------------------------------------------------------------------
# Public API - drop-in replacement for original module
# ---------------------------------------------------------------------------

# Re-export key functions for compatibility
from .toolcall import (
    has_tools,
    build_tool_prompt_block,
    inject_tool_call_context,
    parse_tool_calls_from_text,
)

# Use enhanced sieve by default
ToolCallSieve = EnhancedToolCallSieve


__all__ = [
    "has_tools",
    "build_tool_prompt_block",
    "inject_tool_call_context",
    "parse_tool_calls_from_text",
    "ToolCallSieve",
    "EnhancedToolCallSieve",
    "normalize_dsml_markup",
]
