import os
import json
import asyncio
import logging
import hashlib
from aiokafka import AIOKafkaConsumer
from opentelemetry import trace, metrics
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from mcp.client.sse import sse_client
from mcp import ClientSession
from app.services.extraction import ExtractionEngine
from app.kafka.producer import producer_manager
from app.services.agent_core import GeminiDecider
from app.services.verifier_gate import ConsensusVerifier

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
        self.decider = GeminiDecider()
        self.verifier = ConsensusVerifier()
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
        """Infinite loop consuming events from the Kafka topic, connecting to MCP server."""
        if not self.consumer:
            logger.error("AIOKafkaConsumer not initialized in consume_loop")
            return

        mcp_url = self.crm_erp_url.replace("/api/v1", "/mcp/sse")

        while self._is_running:
            try:
                logger.info("Connecting to MCP Server at %s", mcp_url)
                async with sse_client(mcp_url) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        logger.info("MCP Client Session initialized successfully.")

                        # Get tools list
                        tools_result = await session.list_tools()
                        tools_list = tools_result.tools

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

                                        # Construct idempotency key
                                        idempotency_key = hashlib.sha256(f"{msg.topic}:{msg.partition}:{msg.offset}".encode("utf-8")).hexdigest()

                                        # Wrapper to execute tool via active session
                                        async def execute_tool(action, parameters):
                                            return await self.execute_crm_erp_call(action, parameters, idempotency_key=idempotency_key, session=session)

                                        # Execute the agent loop with self-correcting logic and verifier gate
                                        result = await self.decider.execute_agent_loop(
                                            ticket_text=ticket_text,
                                            order_id=data.get("order_id") or params.order_id,
                                            verifier=self.verifier,
                                            execute_func=execute_tool,
                                            tools=tools_list
                                        )

                                        # Send audit event
                                        audit_data = {
                                            "ticket_id": ticket_id,
                                            "intent": result.get("action", params.intent),
                                            "params": params.model_dump(),
                                            "api_result": result.get("api_result", result)
                                        }
                                        await producer_manager.send_event(self.audit_topic, "ticket_processed", audit_data)
                                        tickets_processed_counter.add(1, {"intent": result.get("action") or "unknown"})
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
                logger.error("Error in MCP Client connection or session: %s. Retrying in 5 seconds...", e)
                if not self._is_running:
                    break
                await asyncio.sleep(5)

    async def execute_crm_erp_call(self, action_or_params, parameters=None, idempotency_key=None, session=None):
        """Invokes the corresponding CRM/ERP endpoint or tool via MCP."""
        action = None
        if parameters is not None:
            action = action_or_params
        else:
            params = action_or_params
            if hasattr(params, "action"):
                action = params.action
                parameters = params.parameters or {}
            else:
                intent = getattr(params, "intent", None) or getattr(params, "action", None)
                if intent == "Update Address":
                    action = "modify_order_address"
                    parameters = {
                        "order_id": getattr(params, "order_id", None),
                        "street_address": getattr(params, "street_address", None),
                        "city": getattr(params, "city", None),
                        "zipcode": getattr(params, "zipcode", None),
                    }
                elif intent == "Check Inventory":
                    action = "check_inventory"
                    parameters = {
                        "item": getattr(params, "item", None),
                        "warehouse": getattr(params, "warehouse", None),
                    }
                elif intent == "Process Return":
                    action = "process_return"
                    parameters = {
                        "order_id": getattr(params, "order_id", None),
                        "quantity": getattr(params, "quantity", None),
                    }
                elif intent == "Upgrade Account":
                    action = "upgrade_customer_tier"
                    parameters = {
                        "customer_id": getattr(params, "customer_id", None),
                        "tier": getattr(params, "tier", None),
                    }
                else:
                    action = str(intent)
                    parameters = getattr(params, "parameters", {}) or {}

        # Map legacy display names/intents to snake_case MCP tool names
        action_map = {
            "Update Address": "modify_order_address",
            "Check Inventory": "check_inventory",
            "Process Return": "process_return",
            "Upgrade Account": "upgrade_customer_tier",
            "Upgrade customer tier": "upgrade_customer_tier",
            "Modify order address": "modify_order_address",
            "Check inventory": "check_inventory",
            "Process return": "process_return"
        }
        if action in action_map:
            action = action_map[action]

        # Use provided active session
        if session is not None:
            try:
                meta = {"idempotency_key": idempotency_key} if idempotency_key else None
                res = await session.call_tool(name=action, arguments=parameters, meta=meta)
                if res.isError:
                    error_msg = getattr(res.content[0], "text", "Unknown MCP error") if res.content else "Unknown MCP error"
                    return {
                        "status_code": 400,
                        "data": {"detail": error_msg}
                    }
                data = {}
                # FIX: Use safe getattr accessors for strict union types
                if res.content:
                    text_content = getattr(res.content[0], "text", None)
                    if text_content is not None:
                        try:
                            data = json.loads(text_content)
                        except Exception:
                            data = {"detail": text_content}
                return {
                    "status_code": 200,
                    "data": data
                }
            except Exception as e:
                logger.exception("Error executing MCP tool call: %s", e)
                return {
                    "status_code": 500,
                    "data": {"detail": str(e)}
                }

        # Otherwise establish transient session (for legacy direct calls)
        mcp_url = self.crm_erp_url.replace("/api/v1", "/mcp/sse")
        try:
            async with sse_client(mcp_url) as (read, write):
                async with ClientSession(read, write) as sess:
                    await sess.initialize()
                    meta = {"idempotency_key": idempotency_key} if idempotency_key else None
                    res = await sess.call_tool(name=action, arguments=parameters, meta=meta)
                    if res.isError:
                        error_msg = getattr(res.content[0], "text", "Unknown MCP error") if res.content else "Unknown MCP error"
                        return {
                            "status_code": 400,
                            "data": {"detail": error_msg}
                        }
                    data = {}
                    # FIX: Use safe getattr accessors here as well
                    if res.content:
                        text_content = getattr(res.content[0], "text", None)
                        if text_content is not None:
                            try:
                                data = json.loads(text_content)
                            except Exception:
                                data = {"detail": text_content}
                    return {
                        "status_code": 200,
                        "data": data
                    }
        except Exception as e:
            logger.exception("Error executing MCP tool call in transient session: %s", e)
            return {
                "status_code": 500,
                "data": {"detail": str(e)}
            }

    async def stop(self):
        """Stops the consumer and closes resources."""
        self._is_running = False
        if self.consumer:
            logger.info("Stopping TicketConsumer")
            await self.consumer.stop()
            await self.extraction_engine.close()
            await self.verifier.close()
