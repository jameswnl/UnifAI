"""
Edge case tests for parser components.

Tests extreme and malformed inputs to validate parser robustness:
- Malformed JSON and tool calls
- Unicode and encoding issues
- Very large inputs
- Nested and complex data structures
- Invalid message formats
- Parser state corruption scenarios
"""

import pytest
import json
from mas.elements.llms.common.chat.message import ChatMessage, Role, ToolCall
from mas.elements.nodes.common.agent.parsers.tool_call_parser import ToolCallParser
from mas.elements.nodes.common.agent.parsers.base import ParseError, ParseErrorType
from mas.elements.nodes.common.agent.primitives import AgentAction, AgentFinish


@pytest.mark.unit
@pytest.mark.agent_system
class TestParserEdgeCases:
    """Edge case tests for parser components."""
    
    @pytest.fixture
    def parser(self):
        """Create parser instance."""
        return ToolCallParser()
    
    def test_extremely_large_content(self, parser):
        """Test parser with extremely large content."""
        from mas.elements.nodes.common.agent.constants import ParserDefaults

        # Test at a large size well within the limit (MAX_CONTENT_LENGTH = 200000)
        large_content = "x" * 100000  # Within the limit
        over_limit_content = "x" * (ParserDefaults.MAX_CONTENT_LENGTH + 1)  # Over the limit

        # Should handle content within the limit
        message_within_limit = ChatMessage(
            role=Role.ASSISTANT,
            content=large_content
        )

        result = parser.parse(message_within_limit)
        assert isinstance(result, AgentFinish)
        assert result.output == large_content

        # Should reject content over the limit
        message_over_limit = ChatMessage(
            role=Role.ASSISTANT,
            content=over_limit_content
        )

        with pytest.raises(ParseError) as exc_info:
            parser.parse(message_over_limit)
        assert exc_info.value.error_type == ParseErrorType.VALIDATION_ERROR
        assert "too long" in str(exc_info.value)
    
    def test_unicode_stress(self, parser):
        """Test parser with various Unicode characters."""
        unicode_content = "🚀🔥💯🎉🌟⚡️🎯🔧🧪📊" * 100
        
        message = ChatMessage(
            role=Role.ASSISTANT,
            content=unicode_content,
            tool_calls=[
                ToolCall(
                    name="unicode_tool",
                    args={"emoji": "🔥", "text": "测试中文", "symbol": "∑∆∇"},
                    tool_call_id="unicode-test"
                )
            ]
        )
        
        result = parser.parse(message)
        assert isinstance(result, list)
        assert len(result) == 1
        
        action = result[0]
        assert action.tool == "unicode_tool"
        assert action.tool_input["emoji"] == "🔥"
        assert action.tool_input["text"] == "测试中文"
        assert action.tool_input["symbol"] == "∑∆∇"
    
    def test_deeply_nested_tool_arguments(self, parser):
        """Test parser with deeply nested tool arguments."""
        nested_args = {
            "level1": {
                "level2": {
                    "level3": {
                        "level4": {
                            "level5": {
                                "data": "deep_value",
                                "array": [1, 2, {"nested": True}],
                                "null_value": None,
                                "boolean": False
                            }
                        }
                    }
                }
            }
        }
        
        message = ChatMessage(
            role=Role.ASSISTANT,
            content="Testing nested arguments",
            tool_calls=[
                ToolCall(
                    name="nested_tool",
                    args=nested_args,
                    tool_call_id="nested-test"
                )
            ]
        )
        
        result = parser.parse(message)
        assert isinstance(result, list)
        assert len(result) == 1
        
        action = result[0]
        assert action.tool == "nested_tool"
        assert action.tool_input["level1"]["level2"]["level3"]["level4"]["level5"]["data"] == "deep_value"
    
    def test_many_tool_calls_boundary(self, parser):
        """Test parser with many tool calls at boundary conditions."""
        from mas.elements.nodes.common.agent.constants import ToolExecutionDefaults

        max_allowed = ToolExecutionDefaults.MAX_TOOL_CALLS_PER_MESSAGE  # 30

        at_limit_tool_calls = [
            ToolCall(
                name=f"tool_{i}",
                args={"index": i, "data": f"value_{i}"},
                tool_call_id=f"call-{i}"
            )
            for i in range(max_allowed)  # At the limit
        ]

        over_limit_tool_calls = [
            ToolCall(
                name=f"tool_{i}",
                args={"index": i, "data": f"value_{i}"},
                tool_call_id=f"call-{i}"
            )
            for i in range(max_allowed + 1)  # Over the limit
        ]

        # Should handle tool calls at the limit
        message_at_limit = ChatMessage(
            role=Role.ASSISTANT,
            content="Tool calls at limit test",
            tool_calls=at_limit_tool_calls
        )

        result = parser.parse(message_at_limit)
        assert isinstance(result, list)
        assert len(result) == max_allowed

        # Verify all tool calls were parsed correctly
        for i, action in enumerate(result):
            assert action.tool == f"tool_{i}"
            assert action.tool_input["index"] == i
            assert action.id == f"call-{i}"

        # Should reject too many tool calls
        message_over_limit = ChatMessage(
            role=Role.ASSISTANT,
            content="Too many tool calls test",
            tool_calls=over_limit_tool_calls
        )

        with pytest.raises(ParseError) as exc_info:
            parser.parse(message_over_limit)
        assert exc_info.value.error_type == ParseErrorType.VALIDATION_ERROR
        assert "Too many tool calls" in str(exc_info.value)
    
    def test_malformed_tool_call_structures(self, parser):
        """Test that malformed tool call structures are rejected by Pydantic validation."""
        from pydantic import ValidationError

        # ToolCall.args is typed as Dict, so Pydantic rejects non-dict values
        # at model construction time
        with pytest.raises(ValidationError):
            ChatMessage(
                role=Role.ASSISTANT,
                content="String args test",
                tool_calls=[
                    ToolCall(
                        name="test_tool",
                        args="should_be_dict_not_string",
                        tool_call_id="string-args"
                    )
                ]
            )
    
    def test_empty_and_none_values(self, parser):
        """Test parser with empty and None values."""
        
        # Empty content with tool calls
        message = ChatMessage(
            role=Role.ASSISTANT,
            content="",  # Empty content
            tool_calls=[
                ToolCall(
                    name="empty_content_tool",
                    args={"param": "value"},
                    tool_call_id="empty-content"
                )
            ]
        )
        
        result = parser.parse(message)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].reasoning == "Using empty_content_tool"  # Uses fallback reasoning
        
        # Empty content (content: str is non-nullable, use "" instead of None)
        message_empty = ChatMessage(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[
                ToolCall(
                    name="none_content_tool",
                    args={"param": "value"},
                    tool_call_id="none-content"
                )
            ]
        )

        result = parser.parse(message_empty)
        assert isinstance(result, list)
        assert len(result) == 1
        assert "none_content_tool" in result[0].reasoning  # Should use fallback reasoning
    
    def test_special_characters_in_tool_names(self, parser):
        """Test parser with special characters in tool names."""
        special_names = [
            "tool-with-dashes",
            "tool_with_underscores",
            "tool.with.dots",
            "tool123numbers",
            "UPPERCASE_TOOL",
            "mixedCaseTool",
            "tool with spaces"  # This might be handled differently
        ]
        
        for tool_name in special_names:
            message = ChatMessage(
                role=Role.ASSISTANT,
                content=f"Testing tool name: {tool_name}",
                tool_calls=[
                    ToolCall(
                        name=tool_name,
                        args={"test": "value"},
                        tool_call_id=f"test-{tool_name.replace(' ', '-')}"
                    )
                ]
            )
            
            result = parser.parse(message)
            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0].tool == tool_name
    
    def test_circular_reference_in_args(self, parser):
        """Test parser with circular references in arguments."""
        # Create args with self-reference (should be handled gracefully)
        args = {"key": "value"}
        # Note: We can't create true circular references in JSON-serializable data
        # But we can test deeply nested structures that might cause issues
        
        recursive_args = {"data": args}
        for i in range(10):  # Create deep nesting
            recursive_args = {"nested": recursive_args, "level": i}
        
        message = ChatMessage(
            role=Role.ASSISTANT,
            content="Testing recursive arguments",
            tool_calls=[
                ToolCall(
                    name="recursive_tool",
                    args=recursive_args,
                    tool_call_id="recursive-test"
                )
            ]
        )
        
        result = parser.parse(message)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].tool == "recursive_tool"
    
    def test_invalid_role_messages(self, parser):
        """Test parser with invalid role messages."""
        
        # Test with USER role (should be ASSISTANT)
        user_message = ChatMessage(
            role=Role.USER,  # Wrong role
            content="This should be from assistant",
            tool_calls=[
                ToolCall(
                    name="test_tool",
                    args={"param": "value"},
                    tool_call_id="wrong-role"
                )
            ]
        )
        
        with pytest.raises(ParseError) as exc_info:
            parser.parse(user_message)
        assert exc_info.value.error_type == ParseErrorType.INVALID_ROLE
    
    def test_mixed_valid_invalid_tool_calls(self, parser):
        """Test parser with mix of valid and invalid tool calls."""
        
        message = ChatMessage(
            role=Role.ASSISTANT,
            content="Mixed valid and invalid tool calls",
            tool_calls=[
                # Valid tool call
                ToolCall(
                    name="valid_tool",
                    args={"param": "value"},
                    tool_call_id="valid-call"
                ),
                # Invalid tool call (empty name)
                ToolCall(
                    name="",  # Invalid
                    args={"param": "value"},
                    tool_call_id="invalid-call"
                ),
                # Another valid tool call
                ToolCall(
                    name="another_valid_tool",
                    args={"param": "value2"},
                    tool_call_id="valid-call-2"
                )
            ]
        )
        
        # Should fail on first invalid tool call
        with pytest.raises(ParseError) as exc_info:
            parser.parse(message)
        assert exc_info.value.error_type == ParseErrorType.TOOL_CALL_ERROR
    
    def test_extremely_long_tool_names_and_ids(self, parser):
        """Test parser with extremely long tool names and IDs."""
        
        long_name = "very_long_tool_name_" + "x" * 1000
        long_id = "very_long_tool_call_id_" + "y" * 1000
        
        message = ChatMessage(
            role=Role.ASSISTANT,
            content="Testing long names and IDs",
            tool_calls=[
                ToolCall(
                    name=long_name,
                    args={"param": "value"},
                    tool_call_id=long_id
                )
            ]
        )
        
        result = parser.parse(message)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].tool == long_name
        assert result[0].id == long_id
    
    def test_parser_state_consistency(self, parser):
        """Test parser state consistency across multiple calls."""
        
        # Parse multiple messages to ensure no state leakage
        messages = [
            ChatMessage(
                role=Role.ASSISTANT,
                content=f"Message {i}",
                tool_calls=[
                    ToolCall(
                        name=f"tool_{i}",
                        args={"index": i},
                        tool_call_id=f"call-{i}"
                    )
                ]
            )
            for i in range(10)
        ]
        
        results = []
        for message in messages:
            result = parser.parse(message)
            results.append(result)
        
        # Each result should be independent
        for i, result in enumerate(results):
            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0].tool == f"tool_{i}"
            assert result[0].tool_input["index"] == i
            assert result[0].id == f"call-{i}"
    
    def test_memory_efficient_parsing(self, parser):
        """Test parser memory efficiency with large inputs."""
        
        # Create a message with large arguments
        large_args = {
            f"key_{i}": "x" * 1000  # 1KB per key
            for i in range(100)  # 100KB total
        }
        
        message = ChatMessage(
            role=Role.ASSISTANT,
            content="Memory efficiency test",
            tool_calls=[
                ToolCall(
                    name="memory_test_tool",
                    args=large_args,
                    tool_call_id="memory-test"
                )
            ]
        )
        
        # Should parse without memory issues
        result = parser.parse(message)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].tool == "memory_test_tool"
        assert len(result[0].tool_input) == 100
    
    def test_concurrent_parser_usage(self, parser):
        """Test parser thread safety with concurrent usage."""
        import threading
        import time
        
        results = []
        errors = []
        
        def parse_message(index):
            try:
                message = ChatMessage(
                    role=Role.ASSISTANT,
                    content=f"Concurrent message {index}",
                    tool_calls=[
                        ToolCall(
                            name=f"concurrent_tool_{index}",
                            args={"thread_id": index},
                            tool_call_id=f"concurrent-{index}"
                        )
                    ]
                )
                
                # Add small delay to increase chance of race conditions
                time.sleep(0.001)
                
                result = parser.parse(message)
                results.append((index, result))
            except Exception as e:
                errors.append((index, str(e)))
        
        # Create multiple threads
        threads = []
        for i in range(10):
            thread = threading.Thread(target=parse_message, args=(i,))
            threads.append(thread)
        
        # Start all threads
        for thread in threads:
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Should have no errors and correct results
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == 10
        
        # Verify each result is correct
        for index, result in results:
            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0].tool == f"concurrent_tool_{index}"
            assert result[0].tool_input["thread_id"] == index
