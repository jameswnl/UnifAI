"""
Unit tests for ToolCallParser.

Tests the tool call parsing functionality including:
- Single and multiple tool call parsing
- Final answer detection and handling
- Error scenarios and validation
- Tool call ID preservation
- Argument validation
"""

import pytest
from mas.elements.llms.common.chat.message import ChatMessage, Role, ToolCall
from mas.elements.nodes.common.agent.parsers.tool_call_parser import ToolCallParser
from mas.elements.nodes.common.agent.primitives import AgentAction, AgentFinish
from mas.elements.nodes.common.agent.parsers import ParseError, ParseErrorType


@pytest.mark.unit
@pytest.mark.agent_system
class TestToolCallParser:
    """Test cases for ToolCallParser implementation."""
    
    @pytest.fixture
    def parser(self):
        """Create ToolCallParser instance."""
        return ToolCallParser()
    
    def test_parse_single_tool_call(self, parser):
        """Test parsing message with single tool call."""
        message = ChatMessage(
            role=Role.ASSISTANT,
            content="I'll search for information.",
            tool_calls=[
                ToolCall(
                    name="search_tool",
                    args={"query": "test query", "limit": 5},
                    tool_call_id="call-123"
                )
            ]
        )
        
        result = parser.parse(message)
        
        assert isinstance(result, list)
        assert len(result) == 1
        
        action = result[0]
        assert isinstance(action, AgentAction)
        assert action.tool == "search_tool"
        assert action.tool_input == {"query": "test query", "limit": 5}
        assert action.id == "call-123"
        assert action.reasoning == "I'll search for information."  # Uses message content as reasoning
    
    def test_parse_multiple_tool_calls(self, parser):
        """Test parsing message with multiple tool calls."""
        message = ChatMessage(
            role=Role.ASSISTANT,
            content="I'll use multiple tools.",
            tool_calls=[
                ToolCall(name="tool1", args={"param1": "value1"}, tool_call_id="call-1"),
                ToolCall(name="tool2", args={"param2": "value2"}, tool_call_id="call-2"),
                ToolCall(name="tool3", args={}, tool_call_id="call-3")
            ]
        )
        
        result = parser.parse(message)
        
        assert isinstance(result, list)
        assert len(result) == 3
        
        # Check each action
        assert result[0].tool == "tool1"
        assert result[0].tool_input == {"param1": "value1"}
        assert result[0].id == "call-1"
        
        assert result[1].tool == "tool2"
        assert result[1].tool_input == {"param2": "value2"}
        assert result[1].id == "call-2"
        
        assert result[2].tool == "tool3"
        assert result[2].tool_input == {}
        assert result[2].id == "call-3"
    
    def test_parse_no_tool_calls_with_content(self, parser):
        """Test parsing message with no tool calls but with content."""
        message = ChatMessage(
            role=Role.ASSISTANT,
            content="This is my final answer. The weather is sunny today and perfect for outdoor activities."
        )
        
        result = parser.parse(message)
        
        assert isinstance(result, AgentFinish)
        assert result.output == message.content
        assert result.reasoning == "No tool calls - providing final answer"
    
    def test_parse_no_tool_calls_empty_content(self, parser):
        """Test parsing message with no tool calls and empty content."""
        message = ChatMessage(
            role=Role.ASSISTANT,
            content=""
        )
        
        result = parser.parse(message)
        
        assert isinstance(result, AgentFinish)
        assert result.output == ""
        assert result.reasoning == "Empty response from LLM"
    
    def test_parse_no_tool_calls_none_content(self, parser):
        """Test parsing message with no tool calls and empty content."""
        message = ChatMessage(
            role=Role.ASSISTANT,
            content=""
        )
        
        result = parser.parse(message)
        
        assert isinstance(result, AgentFinish)
        assert result.output == ""
        assert result.reasoning == "Empty response from LLM"
    
    def test_parse_invalid_tool_args(self, parser):
        """Test that invalid tool arguments (non-dict) are rejected by Pydantic validation."""
        from pydantic import ValidationError

        # ToolCall.args is typed as Dict, so Pydantic rejects non-dict values
        # at model construction time
        with pytest.raises(ValidationError):
            ChatMessage(
                role=Role.ASSISTANT,
                content="Using tool with invalid args.",
                tool_calls=[
                    ToolCall(
                        name="test_tool",
                        args="invalid_args_not_dict",  # Should be dict
                        tool_call_id="call-123"
                    )
                ]
            )
    
    def test_parse_missing_tool_name(self, parser):
        """Test parsing with missing tool name."""
        message = ChatMessage(
            role=Role.ASSISTANT,
            content="Using tool without name.",
            tool_calls=[
                ToolCall(
                    name="",  # Empty name
                    args={"param": "value"},
                    tool_call_id="call-123"
                )
            ]
        )
        
        with pytest.raises(ParseError) as exc_info:
            parser.parse(message)
        
        assert exc_info.value.error_type == ParseErrorType.TOOL_CALL_ERROR
    
    def test_parse_missing_tool_call_id(self, parser):
        """Test parsing with missing tool call ID."""
        message = ChatMessage(
            role=Role.ASSISTANT,
            content="Using tool without ID.",
            tool_calls=[
                ToolCall(
                    name="test_tool",
                    args={"param": "value"},
                    tool_call_id=""  # Empty ID
                )
            ]
        )
        
        with pytest.raises(ParseError) as exc_info:
            parser.parse(message)
        
        assert exc_info.value.error_type == ParseErrorType.TOOL_CALL_ERROR
    
    def test_parse_preserves_tool_call_id(self, parser):
        """Test that parser preserves original tool_call_id."""
        original_id = "function-call-12345678901234567890"
        
        message = ChatMessage(
            role=Role.ASSISTANT,
            content="Testing ID preservation.",
            tool_calls=[
                ToolCall(
                    name="test_tool",
                    args={"query": "test"},
                    tool_call_id=original_id
                )
            ]
        )
        
        result = parser.parse(message)
        
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].id == original_id
    
    def test_parse_with_reasoning_from_content(self, parser):
        """Test that reasoning is extracted from message content."""
        content = "I need to search for information about the weather."
        
        message = ChatMessage(
            role=Role.ASSISTANT,
            content=content,
            tool_calls=[
                ToolCall(
                    name="weather_tool",
                    args={"location": "New York"},
                    tool_call_id="call-123"
                )
            ]
        )
        
        result = parser.parse(message)
        
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].reasoning == content
    
    def test_parse_mixed_valid_invalid_calls(self, parser):
        """Test parsing with mix of valid and invalid tool calls."""
        message = ChatMessage(
            role=Role.ASSISTANT,
            content="Mixed tool calls.",
            tool_calls=[
                ToolCall(name="valid_tool", args={"param": "value"}, tool_call_id="call-1"),
                ToolCall(name="", args={"param": "value"}, tool_call_id="call-2"),  # Invalid
                ToolCall(name="another_valid", args={}, tool_call_id="call-3")
            ]
        )
        
        # Should raise error on first invalid call
        with pytest.raises(ParseError):
            parser.parse(message)
    
    @pytest.mark.parametrize("tool_name", [
        "valid_tool",
        "tool_with_underscore", 
        "tool123",
        "tool-with-dash",
        "tool with space"  # All tool names are valid - no validation required
    ])
    def test_tool_name_acceptance(self, parser, tool_name):
        """Test that various tool name formats are accepted."""
        message = ChatMessage(
            role=Role.ASSISTANT,
            content="Testing tool name acceptance.",
            tool_calls=[
                ToolCall(
                    name=tool_name,
                    args={"param": "value"},
                    tool_call_id="call-123"
                )
            ]
        )
        
        # All tool names should be accepted
        result = parser.parse(message)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].tool == tool_name
    
    def test_error_recovery_information(self, parser):
        """Test that parse errors contain proper recovery information."""
        message = ChatMessage(
            role=Role.ASSISTANT,
            content="Invalid message.",
            tool_calls=[
                ToolCall(name="", args={}, tool_call_id="call-123")
            ]
        )
        
        with pytest.raises(ParseError) as exc_info:
            parser.parse(message)
        
        error = exc_info.value
        assert error.recoverable is True  # Most parsing errors should be recoverable
        assert error.raw_output == "Invalid message."
        assert isinstance(error.error_type, ParseErrorType)
    
    def test_parse_complex_tool_arguments(self, parser):
        """Test parsing with complex nested tool arguments."""
        complex_args = {
            "query": "search term",
            "filters": {
                "date_range": {"start": "2024-01-01", "end": "2024-12-31"},
                "categories": ["tech", "science"],
                "priority": 1
            },
            "options": {
                "include_metadata": True,
                "max_results": 100
            }
        }
        
        message = ChatMessage(
            role=Role.ASSISTANT,
            content="Performing complex search.",
            tool_calls=[
                ToolCall(
                    name="advanced_search",
                    args=complex_args,
                    tool_call_id="call-complex-123"
                )
            ]
        )
        
        result = parser.parse(message)
        
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].tool == "advanced_search"
        assert result[0].tool_input == complex_args
        assert result[0].id == "call-complex-123"
    
    def test_parse_empty_tool_arguments(self, parser):
        """Test parsing with empty tool arguments."""
        message = ChatMessage(
            role=Role.ASSISTANT,
            content="Using tool with no arguments.",
            tool_calls=[
                ToolCall(
                    name="no_args_tool",
                    args={},
                    tool_call_id="call-empty-123"
                )
            ]
        )
        
        result = parser.parse(message)
        
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].tool == "no_args_tool"
        assert result[0].tool_input == {}
        assert result[0].id == "call-empty-123"
    
    def test_parse_maintains_tool_call_order(self, parser):
        """Test that parser maintains tool call order."""
        tool_calls = [
            ToolCall(name=f"tool_{i}", args={"index": i}, tool_call_id=f"call-{i}")
            for i in range(10)
        ]
        
        message = ChatMessage(
            role=Role.ASSISTANT,
            content="Multiple ordered tool calls.",
            tool_calls=tool_calls
        )
        
        result = parser.parse(message)
        
        assert isinstance(result, list)
        assert len(result) == 10
        
        # Verify order is maintained
        for i, action in enumerate(result):
            assert action.tool == f"tool_{i}"
            assert action.tool_input == {"index": i}
            assert action.id == f"call-{i}"
