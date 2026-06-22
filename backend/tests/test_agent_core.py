import pytest
from unittest.mock import AsyncMock
from app.services.agent_core import GeminiDecider, AgentDecision
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
    mock_resp1 = mocker.Mock()
    mock_resp1.text = '{"action": "Process Return", "reasoning": "Return request", "parameters": {"order_id": "ORD-999", "quantity": -5}}'
    mock_resp2 = mocker.Mock()
    mock_resp2.text = '{"action": "Process Return", "reasoning": "Corrected quantity to positive number", "parameters": {"order_id": "ORD-999", "quantity": 5}}'
    
    mock_model.return_value.generate_content.side_effect = [mock_resp1, mock_resp2]
    
    decider = GeminiDecider()
    
    # Mock client endpoint returns a validation error first, then success
    mock_exec = AsyncMock()
    mock_exec.side_effect = [
        {"status_code": 422, "data": {"detail": "quantity must be greater than zero"}},
        {"status_code": 200, "data": {"status": "success"}}
    ]
    
    # Execute loop
    result = await decider.execute_agent_loop(
        ticket_text="I want to return -5 items",
        order_id="ORD-999",
        verifier=None, # bypass consensus check for simplicity
        execute_func=mock_exec
    )
    
    assert result["api_result"]["status_code"] == 200
    assert mock_exec.call_count == 2
