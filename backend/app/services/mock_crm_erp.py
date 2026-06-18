from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import Dict, Any

router = APIRouter()

# --- Mock In-Memory Databases ---
MOCK_ORDERS: Dict[str, Dict[str, Any]] = {
    "ORD-12345": {
        "order_id": "ORD-12345",
        "customer_id": "CUST-001",
        "status": "Processing",
        "address": "123 Main St, London",
        "quantity": 2,
        "item": "Enterprise Server",
        "warehouse": "WH-LON-01",
        "price": 1200.00
    },
    "ORD-67890": {
        "order_id": "ORD-67890",
        "customer_id": "CUST-002",
        "status": "Shipped",
        "address": "456 Oak Rd, Paris",
        "quantity": 1,
        "item": "AI Accelerator",
        "warehouse": "WH-PAR-02",
        "price": 5000.00
    },
    "ORD-99999": {
        "order_id": "ORD-99999",
        "customer_id": "CUST-001",
        "status": "Delivered",
        "address": "789 Pine Ave, Berlin",
        "quantity": 10,
        "item": "Smart Sensors",
        "warehouse": "WH-BER-03",
        "price": 150.00
    }
}

MOCK_INVENTORY: Dict[str, Dict[str, int]] = {
    "Enterprise Server": {"WH-LON-01": 5, "WH-PAR-02": 0, "WH-BER-03": 0},
    "AI Accelerator": {"WH-LON-01": 0, "WH-PAR-02": 2, "WH-BER-03": 1},
    "Smart Sensors": {"WH-LON-01": 20, "WH-PAR-02": 15, "WH-BER-03": 50}
}

MOCK_CUSTOMERS: Dict[str, Dict[str, Any]] = {
    "CUST-001": {
        "customer_id": "CUST-001",
        "name": "Alice Smith",
        "email": "alice@enterprise.com",
        "tier": "Standard",
        "active_deals": 2
    },
    "CUST-002": {
        "customer_id": "CUST-002",
        "name": "Bob Jones",
        "email": "bob@startup.io",
        "tier": "Premium",
        "active_deals": 5
    }
}

MOCK_DEALS: Dict[str, Dict[str, Any]] = {
    "DEAL-101": {
        "deal_id": "DEAL-101",
        "customer_id": "CUST-001",
        "title": "50x Smart Sensors Bulk Purchase",
        "stage": "Discovery",
        "value": 7500.00
    },
    "DEAL-102": {
        "deal_id": "DEAL-102",
        "customer_id": "CUST-002",
        "title": "AI Accelerator Enterprise Licensing",
        "stage": "Proposal",
        "value": 25000.00
    }
}

# --- Pydantic Schemas for Requests ---
class AddressUpdateSchema(BaseModel):
    street_address: str = Field(..., description="The new street address")
    city: str = Field(..., description="The city")
    zipcode: str = Field(..., description="Postal code (must be 5 alphanumeric characters for verification test)")

class DealStageUpdateSchema(BaseModel):
    stage: str = Field(..., description="New deal stage (Discovery, Proposal, Negotiation, Won, Lost)")

class TierUpgradeSchema(BaseModel):
    tier: str = Field(..., description="Target tier (Standard, Premium, Enterprise)")

class ReturnProcessSchema(BaseModel):
    quantity: int = Field(..., gt=0, description="Quantity to return")

# --- Helper Functions to Reset State for Tests ---
def reset_mock_db():
    global MOCK_ORDERS, MOCK_INVENTORY, MOCK_CUSTOMERS, MOCK_DEALS
    # Reset orders to initial state
    MOCK_ORDERS["ORD-12345"]["address"] = "123 Main St, London"
    MOCK_ORDERS["ORD-12345"]["status"] = "Processing"
    MOCK_ORDERS["ORD-67890"]["address"] = "456 Oak Rd, Paris"
    MOCK_ORDERS["ORD-67890"]["status"] = "Shipped"
    MOCK_ORDERS["ORD-99999"]["address"] = "789 Pine Ave, Berlin"
    MOCK_ORDERS["ORD-99999"]["status"] = "Delivered"
    # Reset inventory
    MOCK_INVENTORY["Enterprise Server"] = {"WH-LON-01": 5, "WH-PAR-02": 0, "WH-BER-03": 0}
    # Reset customers
    MOCK_CUSTOMERS["CUST-001"]["tier"] = "Standard"
    MOCK_CUSTOMERS["CUST-002"]["tier"] = "Premium"
    # Reset deals
    MOCK_DEALS["DEAL-101"]["stage"] = "Discovery"
    MOCK_DEALS["DEAL-102"]["stage"] = "Proposal"

# --- ERP Service Routes ---

@router.get("/erp/inventory/{item}", status_code=status.HTTP_200_OK)
async def check_inventory(item: str, warehouse: str):
    """Checks stock of a specific item in a warehouse."""
    if item not in MOCK_INVENTORY:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item '{item}' not found in catalog."
        )
    warehouse_stock = MOCK_INVENTORY[item]
    if warehouse not in warehouse_stock:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid warehouse code '{warehouse}'."
        )
    return {
        "item": item,
        "warehouse": warehouse,
        "stock": warehouse_stock[warehouse]
    }

@router.put("/erp/orders/{order_id}/address", status_code=status.HTTP_200_OK)
async def modify_order_address(order_id: str, address_data: AddressUpdateSchema):
    """Modifies the shipping address of an order if it has not shipped yet."""
    if order_id not in MOCK_ORDERS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order '{order_id}' not found."
        )
    
    order = MOCK_ORDERS[order_id]
    
    # Validation constraint for testing self-correcting retry loop
    if order["status"] == "Shipped":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order has already been shipped. Address modification is blocked."
        )
    if order["status"] == "Delivered":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order has already been delivered. Address modification is blocked."
        )
    
    # Mock zipcode format validation error for testing retry/self-correction
    if len(address_data.zipcode) != 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Zipcode must be exactly 5 characters long. Received format is invalid."
        )
        
    full_address = f"{address_data.street_address}, {address_data.city} {address_data.zipcode}"
    order["address"] = full_address
    return {
        "message": "Order shipping address updated successfully.",
        "order_id": order_id,
        "new_address": full_address,
        "status": order["status"]
    }

@router.post("/erp/orders/{order_id}/invoice", status_code=status.HTTP_201_CREATED)
async def generate_invoice(order_id: str):
    """Generates an invoice for a specific order."""
    if order_id not in MOCK_ORDERS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order '{order_id}' not found."
        )
    order = MOCK_ORDERS[order_id]
    return {
        "invoice_id": f"INV-{order_id.split('-')[-1]}",
        "order_id": order_id,
        "total_amount": order["price"] * order["quantity"],
        "status": "Paid" if order["status"] in ["Shipped", "Delivered"] else "Pending"
    }

@router.post("/erp/orders/{order_id}/return", status_code=status.HTTP_200_OK)
async def process_return(order_id: str, return_data: ReturnProcessSchema):
    """Processes order returns if delivered."""
    if order_id not in MOCK_ORDERS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order '{order_id}' not found."
        )
    order = MOCK_ORDERS[order_id]
    if order["status"] != "Delivered":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Return rejected. Order status is '{order['status']}', returns only accepted for 'Delivered' orders."
        )
    if return_data.quantity > order["quantity"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Return rejected. Quantity requested ({return_data.quantity}) exceeds ordered quantity ({order['quantity']})."
        )
    
    # Process return
    order["quantity"] -= return_data.quantity
    item = order["item"]
    warehouse = order["warehouse"]
    MOCK_INVENTORY[item][warehouse] += return_data.quantity
    
    return {
        "return_id": f"RET-{order_id.split('-')[-1]}",
        "order_id": order_id,
        "item": item,
        "returned_quantity": return_data.quantity,
        "refund_amount": order["price"] * return_data.quantity,
        "status": "Approved"
    }

# --- CRM Service Routes ---

@router.get("/crm/customers/{customer_id}", status_code=status.HTTP_200_OK)
async def get_customer_profile(customer_id: str):
    """Retrieves detailed profile metadata for a customer."""
    if customer_id not in MOCK_CUSTOMERS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer '{customer_id}' not found in CRM database."
        )
    return MOCK_CUSTOMERS[customer_id]

@router.put("/crm/deals/{deal_id}/stage", status_code=status.HTTP_200_OK)
async def modify_deal_stage(deal_id: str, deal_data: DealStageUpdateSchema):
    """Updates the CRM sales deal stage."""
    if deal_id not in MOCK_DEALS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deal '{deal_id}' not found."
        )
    valid_stages = ["Discovery", "Proposal", "Negotiation", "Won", "Lost"]
    if deal_data.stage not in valid_stages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid deal stage '{deal_data.stage}'. Must be one of: {', '.join(valid_stages)}"
        )
    deal = MOCK_DEALS[deal_id]
    deal["stage"] = deal_data.stage
    return {
        "deal_id": deal_id,
        "customer_id": deal["customer_id"],
        "title": deal["title"],
        "new_stage": deal_data.stage,
        "value": deal["value"]
    }

@router.put("/crm/customers/{customer_id}/tier", status_code=status.HTTP_200_OK)
async def upgrade_customer_tier(customer_id: str, tier_data: TierUpgradeSchema):
    """Upgrades a customer's business account tier."""
    if customer_id not in MOCK_CUSTOMERS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer '{customer_id}' not found."
        )
    valid_tiers = ["Standard", "Premium", "Enterprise"]
    if tier_data.tier not in valid_tiers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid account tier '{tier_data.tier}'. Must be one of: {', '.join(valid_tiers)}"
        )
    customer = MOCK_CUSTOMERS[customer_id]
    old_tier = customer["tier"]
    customer["tier"] = tier_data.tier
    return {
        "customer_id": customer_id,
        "customer_name": customer["name"],
        "old_tier": old_tier,
        "new_tier": tier_data.tier,
        "status": "Success"
    }
