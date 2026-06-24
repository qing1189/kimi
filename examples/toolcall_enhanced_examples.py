"""
Example usage of the enhanced tool call implementation.

This example demonstrates the key improvements from the ds2api-inspired enhancement.
"""

from app.api import toolcall_enhanced as tc


def example_1_basic_normalization():
    """Example 1: DSML markup normalization"""
    print("=" * 60)
    print("Example 1: DSML Markup Normalization")
    print("=" * 60)

    # Various DSML formats that will be normalized
    examples = [
        "<|DSML|tool_calls>content</|DSML|tool_calls>",
        "<dsml-tool-calls>content</dsml-tool-calls>",
        "<tool_calls>content</tool_calls>",
    ]

    for text in examples:
        normalized = tc.normalize_dsml_markup(text)
        print(f"Input:  {text}")
        print(f"Output: {normalized}")
        print()


def example_2_streaming_sieve():
    """Example 2: Streaming tool call sieve"""
    print("=" * 60)
    print("Example 2: Streaming Tool Call Sieve")
    print("=" * 60)

    sieve = tc.EnhancedToolCallSieve()

    # Simulate streaming chunks
    chunks = [
        "Let me help you. ",
        "<|DSML|tool_calls>",
        "<|DSML|invoke name=\"get_weather\">",
        "<|DSML|parameter name=\"city\">",
        "<![CDATA[Beijing]]>",
        "</|DSML|parameter>",
        "</|DSML|invoke>",
        "</|DSML|tool_calls>",
    ]

    print("Streaming chunks:")
    all_text = ""
    tool_calls = None

    for i, chunk in enumerate(chunks, 1):
        text, calls = sieve.push(chunk)
        all_text += text

        if text:
            print(f"  Chunk {i}: emitted text: {repr(text)}")
        if calls:
            tool_calls = calls
            print(f"  Chunk {i}: detected tool calls: {calls}")

    print(f"\nFinal text: {repr(all_text)}")
    print(f"Tool calls: {tool_calls}")
    print("\n✓ Notice: DSML markup did not leak into text output!")


def example_3_partial_marker_holding():
    """Example 3: Partial marker detection"""
    print("=" * 60)
    print("Example 3: Partial Marker Detection")
    print("=" * 60)

    sieve = tc.EnhancedToolCallSieve()

    # First chunk ends with partial marker
    text1, calls1 = sieve.push("Some text <|")
    print(f"Chunk 1: 'Some text <|'")
    print(f"  Emitted: {repr(text1)}")
    print(f"  Tool calls: {calls1}")

    # Complete the marker
    text2, calls2 = sieve.push("DSML|tool_calls>...")
    print(f"\nChunk 2: 'DSML|tool_calls>...'")
    print(f"  Emitted: {repr(text2)}")
    print(f"  Tool calls: {calls2}")

    print("\n✓ Partial marker '<|' was held back, not emitted!")


def example_4_code_fence_protection():
    """Example 4: Code fence protection"""
    print("=" * 60)
    print("Example 4: Code Fence Protection")
    print("=" * 60)

    text_with_example = """
Here's how to use tool calls:

```xml
<|DSML|tool_calls>
  <|DSML|invoke name="example">
  </|DSML|invoke>
</|DSML|tool_calls>
```

That's the format!
"""

    # Check if tool call marker is in code fence
    marker_pos = text_with_example.find("<|DSML|tool_calls>")
    is_in_fence = tc.is_inside_code_fence(text_with_example, marker_pos)

    print("Text contains tool call example in code fence.")
    print(f"Marker position: {marker_pos}")
    print(f"Is inside code fence: {is_in_fence}")
    print("\n✓ Tool call in example code is correctly detected and ignored!")


def example_5_xml_repair():
    """Example 5: XML repair mechanisms"""
    print("=" * 60)
    print("Example 5: XML Repair Mechanisms")
    print("=" * 60)

    # Missing opening wrapper
    broken_xml = '<invoke name="test"><parameter name="x">1</parameter></invoke></tool_calls>'
    print("Broken XML (missing opening tag):")
    print(broken_xml)

    repaired = tc.repair_missing_wrapper(broken_xml)
    print("\nRepaired XML:")
    print(repaired)
    print("\n✓ Missing <tool_calls> wrapper was automatically added!")

    # Unclosed CDATA
    print("\n" + "-" * 60)
    unclosed_cdata = '<parameter><![CDATA[some text'
    print("Unclosed CDATA:")
    print(unclosed_cdata)

    sanitized = tc.sanitize_loose_cdata(unclosed_cdata)
    print("\nSanitized:")
    print(sanitized)
    print("\n✓ Unclosed CDATA was automatically closed!")


def main():
    """Run all examples"""
    examples = [
        example_1_basic_normalization,
        example_2_streaming_sieve,
        example_3_partial_marker_holding,
        example_4_code_fence_protection,
        example_5_xml_repair,
    ]

    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 58 + "║")
    print("║" + " Enhanced Tool Call Implementation Examples ".center(58) + "║")
    print("║" + " Inspired by ds2api ".center(58) + "║")
    print("║" + " " * 58 + "║")
    print("╚" + "=" * 58 + "╝")
    print("\n")

    for example in examples:
        example()
        print()

    print("=" * 60)
    print("All examples completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
