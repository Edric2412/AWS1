import logging
from typing import Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel.server import request_ctx
from fastapi import HTTPException

from app.services.mock_crm_erp import (
    check_inventory as mock_check_inventory,
    modify_order_address as mock_modify_order_address,
    generate_invoice as mock_generate_invoice,
    process_return as mock_process_return,
    get_customer_profile as mock_get_customer_profile,
    modify_deal_stage as mock_modify_deal_stage,
    upgrade_customer_tier as mock_upgrade_customer_tier,
    AddressUpdateSchema,
    DealStageUpdateSchema,
    TierUpgradeSchema,
    ReturnProcessSchema
)

logger = logging.getLogger("syncops.mcp_server")

# Instantiate FastMCP server
mcp = FastMCP("SyncOps ERP CRM Server")

# In-memory store for idempotency verification
PROCESSED_MUTATIONS: Dict[str, Any] = {}

def get_idempotency_key() -> Optional[str]:
    """Retrieves the idempotency key from JSON-RPC metadata if present."""
    try:
        ctx = request_ctx.get()
        if ctx and ctx.meta and hasattr(ctx.meta, "model_extra") and ctx.meta.model_extra:
            return ctx.meta.model_extra.get("idempotency_key")
    except Exception:
        pass
    return None

def check_idempotency(key: Optional[str]) -> Optional[Any]:
    if key and key in PROCESSED_MUTATIONS:
        logger.info(f"Idempotency hit for key: {key}. Returning cached response.")
        return PROCESSED_MUTATIONS[key]
    return None

def save_idempotency(key: Optional[str], result: Any):
    if key:
        PROCESSED_MUTATIONS[key] = result

@mcp.tool()
async def check_inventory(item: str, warehouse: str) -> dict:
    """Checks stock of a specific item in a warehouse."""
    try:
        return await mock_check_inventory(item, warehouse)
    except HTTPException as e:
        raise ValueError(e.detail)

@mcp.tool()
async def modify_order_address(order_id: str, street_address: str, city: str, zipcode: str) -> dict:
    """Modifies the shipping address of an order if it has not shipped yet."""
    ikey = get_idempotency_key()
    cached = check_idempotency(ikey)
    if cached is not None:
        return cached

    try:
        address_data = AddressUpdateSchema(
            street_address=street_address,
            city=city,
            zipcode=zipcode
        )
        res = await mock_modify_order_address(order_id, address_data)
        save_idempotency(ikey, res)
        return res
    except HTTPException as e:
        raise ValueError(e.detail)

@mcp.tool()
async def generate_invoice(order_id: str) -> dict:
    """Generates an invoice for a specific order."""
    ikey = get_idempotency_key()
    cached = check_idempotency(ikey)
    if cached is not None:
        return cached

    try:
        res = await mock_generate_invoice(order_id)
        save_idempotency(ikey, res)
        return res
    except HTTPException as e:
        raise ValueError(e.detail)

@mcp.tool()
async def process_return(order_id: str, quantity: int) -> dict:
    """Processes order returns if delivered."""
    ikey = get_idempotency_key()
    cached = check_idempotency(ikey)
    if cached is not None:
        return cached

    try:
        return_data = ReturnProcessSchema(quantity=quantity)
        res = await mock_process_return(order_id, return_data)
        save_idempotency(ikey, res)
        return res
    except HTTPException as e:
        raise ValueError(e.detail)

@mcp.tool()
async def get_customer_profile(customer_id: str) -> dict:
    """Retrieves detailed profile metadata for a customer."""
    try:
        return await mock_get_customer_profile(customer_id)
    except HTTPException as e:
        raise ValueError(e.detail)

@mcp.tool()
async def modify_deal_stage(deal_id: str, stage: str) -> dict:
    """Updates the CRM sales deal stage."""
    ikey = get_idempotency_key()
    cached = check_idempotency(ikey)
    if cached is not None:
        return cached

    try:
        deal_data = DealStageUpdateSchema(stage=stage)
        res = await mock_modify_deal_stage(deal_id, deal_data)
        save_idempotency(ikey, res)
        return res
    except HTTPException as e:
        raise ValueError(e.detail)

@mcp.tool()
async def upgrade_customer_tier(customer_id: str, tier: str) -> dict:
    """Upgrades a customer's business account tier."""
    ikey = get_idempotency_key()
    cached = check_idempotency(ikey)
    if cached is not None:
        return cached

    try:
        tier_data = TierUpgradeSchema(tier=tier)
        res = await mock_upgrade_customer_tier(customer_id, tier_data)
        save_idempotency(ikey, res)
        return res
    except HTTPException as e:
        raise ValueError(e.detail)
