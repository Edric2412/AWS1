import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.kafka.producer import producer_manager
from app.kafka.consumers.ticket_consumer import TicketConsumer
from app.services.extraction import ExtractedTicketParams

def test_ingest_ticket_endpoint(mocker):
    """Verifies that the /ingest endpoint publishes the ticket_received event."""
    mock_send = mocker.patch.object(producer_manager, "send_event", new_callable=mocker.AsyncMock)
    
    client = TestClient(app)
    response = client.post(
        "/api/v1/tickets/ingest",
        json={"ticket_text": "Please update my address to 123 Main St for order ORD-55555"}
    )
    
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "success"
    assert "ticket_id" in res_data
    
    # Assert send_event was called with correct parameters
    mock_send.assert_called_once()
    args = mock_send.call_args[0]
    assert args[0] == "tickets"
    assert args[1] == "ticket_received"
    assert args[2]["ticket_text"] == "Please update my address to 123 Main St for order ORD-55555"

@pytest.mark.asyncio
async def test_ticket_consumer_calls_crm_erp(mocker):
    """Verifies that the ticket consumer properly translates parsed intents into CRM/ERP mock API calls."""
    consumer = TicketConsumer()
    
    # Mock extraction engine
    extracted_params = ExtractedTicketParams(
        intent="Update Address",
        order_id="ORD-12345",
        street_address="789 Pine Ave",
        city="Chicago",
        zipcode="60601"
    )
    mocker.patch.object(consumer.extraction_engine, "extract_parameters", return_value=extracted_params)
    
    # Mock httpx AsyncClient call
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "success", "message": "Address updated"}
    
    # Mock httpx PUT request
    mocker.patch("httpx.AsyncClient.put", new_callable=mocker.AsyncMock, return_value=mock_response)
    
    # Mock audit sending
    mocker.patch.object(producer_manager, "send_event", new_callable=mocker.AsyncMock)
    
    # Test execute_crm_erp_call directly
    res = await consumer.execute_crm_erp_call(extracted_params)
    
    assert res["status_code"] == 200
    assert res["method"] == "PUT"
    assert "orders/ORD-12345/address" in res["url"]
    
    # Clean up
    await consumer.extraction_engine.close()
