from contextlib import asynccontextmanager
import logging
import uuid

from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv

from app.kafka.consumers.audit_consumer import AuditConsumer
from app.kafka.consumers.ticket_consumer import TicketConsumer
from app.kafka.producer import producer_manager
from app.services.mock_crm_erp import router as mock_router
from app.telemetry import init_telemetry

# Call load_dotenv here after all imports are safely resolved
load_dotenv()

logger = logging.getLogger("syncops.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting SyncOps AI Backend Services")
    ticket_consumer = TicketConsumer()
    audit_consumer = AuditConsumer()
    
    # Start Kafka Producer
    try:
        await producer_manager.start()
        logger.info("Kafka Producer started successfully.")
    except Exception as e:
        logger.error("Failed to start Kafka Producer: %s. Event publishing will be unavailable.", e)

    # Start Ticket Consumer
    try:
        await ticket_consumer.start()
        logger.info("Kafka Ticket Consumer started successfully.")
    except Exception as e:
        logger.error("Failed to start Kafka Ticket Consumer: %s. Ticket processing will be unavailable.", e)

    # Start Audit Consumer
    try:
        await audit_consumer.start()
        logger.info("Kafka Audit Consumer started successfully.")
    except Exception as e:
        logger.error("Failed to start Kafka Audit Consumer: %s. Audit logging will be unavailable.", e)

    yield
    
    # Shutdown
    logger.info("Shutting down SyncOps AI Backend Services")
    try:
        await producer_manager.stop()
    except Exception as e:
        logger.error("Error stopping Kafka Producer: %s", e)
        
    try:
        await ticket_consumer.stop()
    except Exception as e:
        logger.error("Error stopping Kafka Ticket Consumer: %s", e)
        
    try:
        await audit_consumer.stop()
    except Exception as e:
        logger.error("Error stopping Kafka Audit Consumer: %s", e)

app = FastAPI(
    title="SyncOps AI - Mock Sandbox and Backend API",
    description="Mock sandbox environments and orchestration API for Support and Order Fulfillment agent automation.",
    version="1.0.0",
    lifespan=lifespan
)

# Initialize OpenTelemetry
init_telemetry(app)

# Mount the mock CRM & ERP router
app.include_router(mock_router, prefix="/api/v1", tags=["sandbox"])

class TicketIngestRequest(BaseModel):
    ticket_text: str

@app.post("/api/v1/tickets/ingest", tags=["ingest"])
async def ingest_ticket(request: TicketIngestRequest):
    """Publishes a ticket text message to the Redpanda/Kafka 'tickets' topic."""
    ticket_id = f"TCK-{uuid.uuid4().hex[:8].upper()}"
    event_data = {
        "ticket_id": ticket_id,
        "ticket_text": request.ticket_text
    }
    try:
        await producer_manager.send_event("tickets", "ticket_received", event_data)
        return {
            "status": "success",
            "ticket_id": ticket_id,
            "message": "Ticket successfully published to Redpanda"
        }
    except Exception as e:
        logger.exception("Failed to publish ticket event to Kafka")
        return {
            "status": "error",
            "message": f"Failed to publish event to Redpanda: {e}"
        }

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "SyncOps AI Backend Sandbox",
        "version": "1.0.0"
    }
