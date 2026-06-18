import pytest
from app.services.extraction import ExtractionEngine, ExtractedTicketParams

@pytest.mark.asyncio
async def test_extract_with_vllm_success(mocker):
    engine = ExtractionEngine()
    
    # Mock successful HTTP POST to vLLM
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": '{"intent": "Update Address", "order_id": "ORD-12345", "street_address": "456 Oak Rd", "city": "Paris", "zipcode": "75001"}'
                }
            }
        ]
    }
    
    mocker.patch.object(engine.client, "post", return_value=mock_response)
    
    result = await engine.extract_with_vllm("Please update my address to 456 Oak Rd, Paris 75001 for order ORD-12345.")
    assert result is not None
    assert result.intent == "Update Address"
    assert result.order_id == "ORD-12345"
    assert result.street_address == "456 Oak Rd"
    assert result.zipcode == "75001"
    
    await engine.close()

@pytest.mark.asyncio
async def test_extract_with_ollama_success(mocker):
    engine = ExtractionEngine()
    
    # Mock successful HTTP POST to Ollama
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "response": '{"intent": "Check Inventory", "item": "AI Accelerator", "warehouse": "WH-PAR-02"}'
    }
    
    mocker.patch.object(engine.client, "post", return_value=mock_response)
    
    result = await engine.extract_with_ollama("Is there any stock of AI Accelerator in the Paris warehouse WH-PAR-02?")
    assert result is not None
    assert result.intent == "Check Inventory"
    assert result.item == "AI Accelerator"
    assert result.warehouse == "WH-PAR-02"
    
    await engine.close()

@pytest.mark.asyncio
async def test_extract_routing_fallback_to_ollama(mocker):
    engine = ExtractionEngine()
    
    # Mock vLLM failing (raise connection error)
    mocker.patch.object(engine, "extract_with_vllm", return_value=None)
    
    # Mock Ollama succeeding
    expected_result = ExtractedTicketParams(intent="Generate Invoice", order_id="ORD-12345")
    mocker.patch.object(engine, "extract_with_ollama", return_value=expected_result)
    
    result = await engine.extract_parameters("Can you generate an invoice for ORD-12345?")
    assert result == expected_result
    
    await engine.close()

@pytest.mark.asyncio
async def test_extract_routing_fallback_to_heuristic(mocker):
    engine = ExtractionEngine()
    
    # Mock both vLLM and Ollama failing
    mocker.patch.object(engine, "extract_with_vllm", return_value=None)
    mocker.patch.object(engine, "extract_with_ollama", return_value=None)
    
    ticket = "I would like to process a return of 3 items for order ORD-99999 from the Berlin warehouse WH-BER-03."
    result = await engine.extract_parameters(ticket)
    
    assert result.intent == "Process Return"
    assert result.order_id == "ORD-99999"
    assert result.warehouse == "WH-BER-03"
    assert result.quantity == 3
    
    await engine.close()

def test_heuristic_fallback_update_address():
    engine = ExtractionEngine()
    ticket = "I moved to 555 New Way, London, zipcode 54321, update order ORD-12345 please"
    result = engine._heuristic_fallback(ticket)
    
    assert result.intent == "Update Address"
    assert result.order_id == "ORD-12345"
    assert result.street_address == "555 New Way"
    assert result.city == "London"
    assert result.zipcode == "54321"

def test_heuristic_fallback_upgrade_account():
    engine = ExtractionEngine()
    ticket = "Customer CUST-002 wishes to upgrade their plan to enterprise tier"
    result = engine._heuristic_fallback(ticket)
    
    assert result.intent == "Upgrade Account"
    assert result.customer_id == "CUST-002"
    assert result.tier == "Enterprise"
