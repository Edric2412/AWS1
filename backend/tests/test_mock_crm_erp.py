import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.mock_crm_erp import reset_mock_db, MOCK_ORDERS, MOCK_INVENTORY, MOCK_CUSTOMERS, MOCK_DEALS

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    reset_mock_db()
    yield

def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "online"

# --- ERP Tests ---

def test_check_inventory_success():
    response = client.get("/api/v1/erp/inventory/Enterprise Server?warehouse=WH-LON-01")
    assert response.status_code == 200
    data = response.json()
    assert data["item"] == "Enterprise Server"
    assert data["warehouse"] == "WH-LON-01"
    assert data["stock"] == 5

def test_check_inventory_invalid_item():
    response = client.get("/api/v1/erp/inventory/Nonexistent Item?warehouse=WH-LON-01")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

def test_check_inventory_invalid_warehouse():
    response = client.get("/api/v1/erp/inventory/Enterprise Server?warehouse=WH-INVALID")
    assert response.status_code == 400
    assert "invalid warehouse" in response.json()["detail"].lower()

def test_modify_order_address_processing_success():
    payload = {
        "street_address": "999 Tech Blvd",
        "city": "London",
        "zipcode": "EC1A2"
    }
    response = client.put("/api/v1/erp/orders/ORD-12345/address", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["order_id"] == "ORD-12345"
    assert data["new_address"] == "999 Tech Blvd, London EC1A2"
    assert MOCK_ORDERS["ORD-12345"]["address"] == "999 Tech Blvd, London EC1A2"

def test_modify_order_address_shipped_blocked():
    payload = {
        "street_address": "555 New Way",
        "city": "Paris",
        "zipcode": "75001"
    }
    # ORD-67890 is already 'Shipped'
    response = client.put("/api/v1/erp/orders/ORD-67890/address", json=payload)
    assert response.status_code == 400
    assert "already been shipped" in response.json()["detail"].lower()

def test_modify_order_address_invalid_zipcode():
    payload = {
        "street_address": "123 Main St",
        "city": "London",
        "zipcode": "TOO_LONG_ZIP"
    }
    # Zipcode must be exactly 5 chars
    response = client.put("/api/v1/erp/orders/ORD-12345/address", json=payload)
    assert response.status_code == 422
    assert "zipcode must be exactly 5 characters" in response.json()["detail"].lower()

def test_generate_invoice():
    response = client.post("/api/v1/erp/orders/ORD-12345/invoice")
    assert response.status_code == 201
    data = response.json()
    assert data["order_id"] == "ORD-12345"
    assert data["invoice_id"] == "INV-12345"
    assert data["total_amount"] == 2400.00  # 1200 * 2
    assert data["status"] == "Pending"

def test_process_return_success():
    payload = {"quantity": 2}
    # ORD-99999 is 'Delivered' and has quantity 10
    response = client.post("/api/v1/erp/orders/ORD-99999/return", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["order_id"] == "ORD-99999"
    assert data["returned_quantity"] == 2
    assert data["refund_amount"] == 300.00  # 150 * 2
    assert MOCK_ORDERS["ORD-99999"]["quantity"] == 8
    assert MOCK_INVENTORY["Smart Sensors"]["WH-BER-03"] == 52  # 50 + 2

def test_process_return_not_delivered():
    payload = {"quantity": 1}
    # ORD-12345 is 'Processing', not 'Delivered'
    response = client.post("/api/v1/erp/orders/ORD-12345/return", json=payload)
    assert response.status_code == 400
    assert "only accepted for 'delivered' orders" in response.json()["detail"].lower()

# --- CRM Tests ---

def test_get_customer_profile_success():
    response = client.get("/api/v1/crm/customers/CUST-001")
    assert response.status_code == 200
    assert response.json()["name"] == "Alice Smith"

def test_get_customer_profile_not_found():
    response = client.get("/api/v1/crm/customers/CUST-999")
    assert response.status_code == 404

def test_modify_deal_stage_success():
    payload = {"stage": "Negotiation"}
    response = client.put("/api/v1/crm/deals/DEAL-101/stage", json=payload)
    assert response.status_code == 200
    assert response.json()["new_stage"] == "Negotiation"
    assert MOCK_DEALS["DEAL-101"]["stage"] == "Negotiation"

def test_modify_deal_stage_invalid():
    payload = {"stage": "InvalidStage"}
    response = client.put("/api/v1/crm/deals/DEAL-101/stage", json=payload)
    assert response.status_code == 400

def test_upgrade_customer_tier():
    payload = {"tier": "Enterprise"}
    response = client.put("/api/v1/crm/customers/CUST-001/tier", json=payload)
    assert response.status_code == 200
    assert response.json()["new_tier"] == "Enterprise"
    assert MOCK_CUSTOMERS["CUST-001"]["tier"] == "Enterprise"
