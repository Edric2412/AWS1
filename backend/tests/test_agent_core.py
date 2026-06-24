import pytest
from unittest.mock import AsyncMock
from app.services.agent_core import GeminiDecider
from app.services.verifier_gate import ConsensusVerifier

@pytest.mark.asyncio
async def test_make_decision_success(mocker):
    # Mock Gemini API Client BEFORE instantiating GeminiDecider
    mock_model = mocker.patch("app.services.agent_core.genai.GenerativeModel")
    mock_response = mocker.Mock()
    mock_response.text = '{"action": "Update Address", "reasoning": "User requested delivery address update", "parameters": {"street_address": "123 Elm St", "city": "London", "zipcode": "EC1A 1BB"}}'
    mock_model.return_value.generate_content.return_value = mock_response
    
    decider = GeminiDecider()
    ticket = "I moved to 123 Elm St, London, EC1A 1BB. Update my order ORD-999 please."
    decision = await decider.make_decision(ticket, "ORD-999")
    
    assert decision.action == "Update Address"
    assert decision.parameters["zipcode"] == "EC1A 1BB"


@pytest.mark.asyncio
async def test_verifier_consensus_match(mocker):
    verifier = ConsensusVerifier()
    
    # Mock Ollama returning matching decision
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "response": '{"action": "Update Address", "is_safe": true}'
    }
    mocker.patch.object(verifier.client, "post", return_value=mock_response)
    
    ticket = "Please update my address to 123 Elm St, London."
    proposed_action = "Update Address"
    
    is_agreed = await verifier.verify_action(ticket, proposed_action)
    assert is_agreed is True
    await verifier.close()


@pytest.mark.asyncio
async def test_self_correcting_retry_loop(mocker):
    # Mock Gemini API Client
    mock_model = mocker.patch("app.services.agent_core.genai.GenerativeModel")
    
    # Mock first response (failure) with function call
    mock_fc1 = mocker.Mock()
    mock_fc1.name = "process_return"
    mock_fc1.args = {"order_id": "ORD-999", "quantity": -5}
    
    mock_part1 = mocker.Mock()
    mock_part1.function_call = mock_fc1
    
    mock_content1 = mocker.Mock()
    mock_content1.parts = [mock_part1]
    
    mock_candidate1 = mocker.Mock()
    mock_candidate1.content = mock_content1
    
    mock_resp1 = mocker.Mock()
    mock_resp1.candidates = [mock_candidate1]
    
    # Mock second response (corrected success) with function call
    mock_fc2 = mocker.Mock()
    mock_fc2.name = "process_return"
    mock_fc2.args = {"order_id": "ORD-999", "quantity": 5}
    
    mock_part2 = mocker.Mock()
    mock_part2.function_call = mock_fc2
    
    mock_content2 = mocker.Mock()
    mock_content2.parts = [mock_part2]
    
    mock_candidate2 = mocker.Mock()
    mock_candidate2.content = mock_content2
    
    mock_resp2 = mocker.Mock()
    mock_resp2.candidates = [mock_candidate2]
    
    mock_model.return_value.generate_content.side_effect = [mock_resp1, mock_resp2]
    
    decider = GeminiDecider()
    
    # Mock client endpoint returns a validation error first, then success
    mock_exec = AsyncMock()
    mock_exec.side_effect = [
        {"status_code": 422, "data": {"detail": "quantity must be greater than zero"}},
        {"status_code": 200, "data": {"status": "success"}}
    ]
    
    tools = [
        {
            "name": "process_return",
            "description": "Process a return",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "quantity": {"type": "integer"}
                },
                "required": ["order_id", "quantity"]
            }
        }
    ]
    
    # Execute loop
    result = await decider.execute_agent_loop(
        ticket_text="I want to return -5 items",
        order_id="ORD-999",
        verifier=None, # bypass consensus check for simplicity
        execute_func=mock_exec,
        tools=tools
    )
    
    assert result["api_result"]["status_code"] == 200
    assert mock_exec.call_count == 2
