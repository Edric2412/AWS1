import os
import json
import asyncio
import logging
from aiokafka import AIOKafkaConsumer
from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

logger = logging.getLogger("syncops.kafka.consumers.audit")
tracer = trace.get_tracer("syncops.kafka.consumers.audit")

class AuditConsumer:
    def __init__(self):
        self.bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        self.topic = os.getenv("AUDIT_TOPIC", "audit")
        self.consumer = None
        self._is_running = False

    async def start(self):
        """Starts the Kafka audit consumer and run loop."""
        logger.info("Starting AuditConsumer subscribing to %s", self.topic)
        self.consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id="audit-trail-group",
            auto_offset_reset="earliest",
            value_deserializer=lambda m: json.loads(m.decode("utf-8"))
        )
        await self.consumer.start()
        self._is_running = True
        asyncio.create_task(self.consume_loop())

    async def consume_loop(self):
        """Infinite loop consuming audit events from the Kafka topic."""
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
                    
                    with tracer.start_as_current_span("audit_log_event", context=context) as span:
                        event = msg.value
                        event_type = event.get("event_type")
                        data = event.get("data", {})
                        
                        span.set_attribute("kafka.offset", msg.offset)
                        span.set_attribute("kafka.partition", msg.partition)
                        span.set_attribute("audit.event_type", event_type)
                        
                        logger.info("[AUDIT TRAIL] Event: %s | Data: %s", event_type, json.dumps(data))
                except Exception:
                    logger.exception("Error processing audit event")
        except Exception as e:
            logger.exception("Exception in audit consume_loop")

    async def stop(self):
        """Stops the consumer and closes resources."""
        self._is_running = False
        if self.consumer:
            logger.info("Stopping AuditConsumer")
            await self.consumer.stop()
