import os
import json
import asyncio
import logging
import httpx
from aiokafka import AIOKafkaConsumer
from opentelemetry import trace, metrics
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from app.services.extraction import ExtractionEngine
from app.kafka.producer import producer_manager

logger = logging.getLogger("syncops.kafka.consumers.ticket")
tracer = trace.get_tracer("syncops.kafka.consumers.ticket")
meter = metrics.get_meter("syncops.kafka.consumers.ticket")

# Metrics definitions
tickets_processed_counter = meter.create_counter(
    "tickets.processed",
    description="Number of tickets processed by the consumer",
    unit="1"
)
tickets_failed_counter = meter.create_counter(
    "tickets.failed",
    description="Number of tickets that failed processing",
    unit="1"
)

class TicketConsumer:
    def __init__(self):
        self.bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        self.topic = os.getenv("TICKET_TOPIC", "tickets")
        self.audit_topic = os.getenv("AUDIT_TOPIC", "audit")
        self.crm_erp_url = os.getenv("MOCK_CRM_ERP_URL", "http://localhost:8000/api/v1")
        self.extraction_engine = ExtractionEngine()
        self.consumer = None
        self._is_running = False

    async def start(self):
        """Starts the Kafka consumer and run loop."""
        logger.info("Starting TicketConsumer subscribing to %s", self.topic)
        self.consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id="ticket-processor-group",
            auto_offset_reset="earliest",
            value_deserializer=lambda m: json.loads(m.decode("utf-8"))
        )
        await self.consumer.start()
        self._is_running = True
        asyncio.create_task(self.consume_loop())

    async def consume_loop(self):
        """Infinite loop consuming events from the Kafka topic."""
        try:
            async for msg in self.consumer:
                if not self._is_running:
                    break
                try:
                    # Extract OTel context from headers
                    carrier = {}
                    if msg.headers:
                        for key, val in msg.headers:
                            carrier[key] = val.decode("utf-8")
                    
                    context = TraceContextTextMapPropagator().extract(carrier=carrier)
                    
                    # Process inside a span linked to the publisher context
                    with tracer.start_as_current_span("process_ticket_event", context=context) as span:
                        event = msg.value
                        event_type = event.get("event_type")
                        data = event.get("data", {})
                        
                        span.set_attribute("kafka.offset", msg.offset)
                        span.set_attribute("kafka.partition", msg.partition)
                        span.set_attribute("ticket.event_type", event_type)
                        
                        if event_type == "ticket_received":
                            ticket_text = data.get("ticket_text")
                            ticket_id = data.get("ticket_id")
                            span.set_attribute("ticket.id", ticket_id)
                            
                            logger.info("Processing ticket %s: %s", ticket_id, ticket_text)
                            
                            # Extract parameters
                            params = await self.extraction_engine.extract_parameters(ticket_text)
                            span.set_attribute("extraction.intent", params.intent or "unknown")
                            
                            # Call mock API based on intent
                            result = await self.execute_crm_erp_call(params)
                            
                            # Send audit event
                            audit_data = {
                                "ticket_id": ticket_id,
                                "intent": params.intent,
                                "params": params.model_dump(),
                                "api_result": result
                            }
                            await producer_manager.send_event(self.audit_topic, "ticket_processed", audit_data)
                            tickets_processed_counter.add(1, {"intent": params.intent or "unknown"})
                        else:
                            logger.warning("Unknown event type: %s", event_type)
                            
                except Exception as e:
                    logger.exception("Error processing ticket event")
                    tickets_failed_counter.add(1)
                    try:
                        await producer_manager.send_event(self.audit_topic, "ticket_failed", {"error": str(e)})
                    except Exception:
                        logger.exception("Failed to publish ticket_failed audit event")
        except Exception as e:
            logger.exception("Exception in consume_loop")

    async def execute_crm_erp_call(self, params):
        """Invokes the corresponding CRM/ERP endpoint."""
        async with httpx.AsyncClient() as client:
            intent = params.intent
            if intent == "Update Address":
                if not params.order_id:
                    return {"status": "error", "message": "Missing order_id"}
                payload = {
                    "street_address": params.street_address,
                    "city": params.city,
                    "zipcode": params.zipcode
                }
                url = f"{self.crm_erp_url}/orders/{params.order_id}/address"
                logger.info("Calling PUT %s with %s", url, payload)
                response = await client.put(url, json=payload)
                return {"method": "PUT", "url": url, "status_code": response.status_code, "data": response.json()}
                
            elif intent == "Check Inventory":
                if not params.item:
                    return {"status": "error", "message": "Missing item"}
                url = f"{self.crm_erp_url}/inventory/{params.item}"
                req_params = {}
                if params.warehouse:
                    req_params["warehouse"] = params.warehouse
                logger.info("Calling GET %s with params %s", url, req_params)
                response = await client.get(url, params=req_params)
                return {"method": "GET", "url": url, "status_code": response.status_code, "data": response.json()}
                
            elif intent == "Process Return":
                if not params.order_id:
                    return {"status": "error", "message": "Missing order_id"}
                payload = {
                    "quantity": params.quantity,
                    "warehouse": params.warehouse
                }
                url = f"{self.crm_erp_url}/orders/{params.order_id}/return"
                logger.info("Calling POST %s with %s", url, payload)
                response = await client.post(url, json=payload)
                return {"method": "POST", "url": url, "status_code": response.status_code, "data": response.json()}
                
            elif intent == "Upgrade Account":
                if not params.customer_id:
                    return {"status": "error", "message": "Missing customer_id"}
                payload = {
                    "tier": params.tier
                }
                url = f"{self.crm_erp_url}/customers/{params.customer_id}/upgrade"
                logger.info("Calling POST %s with %s", url, payload)
                response = await client.post(url, json=payload)
                return {"method": "POST", "url": url, "status_code": response.status_code, "data": response.json()}
                
            else:
                return {"status": "skipped", "message": f"Unsupported or unknown intent: {intent}"}

    async def stop(self):
        """Stops the consumer and closes resources."""
        self._is_running = False
        if self.consumer:
            logger.info("Stopping TicketConsumer")
            await self.consumer.stop()
            await self.extraction_engine.close()
