import os
import json
import logging
from aiokafka import AIOKafkaProducer
from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

logger = logging.getLogger("syncops.kafka.producer")
tracer = trace.get_tracer("syncops.kafka.producer")

class KafkaProducerManager:
    def __init__(self):
        self.bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        self.producer = None

    async def start(self):
        """Starts the Kafka producer if not already started."""
        if not self.producer:
            logger.info("Starting AIOKafkaProducer with servers: %s", self.bootstrap_servers)
            self.producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8")
            )
            await self.producer.start()

    async def stop(self):
        """Stops the Kafka producer."""
        if self.producer:
            logger.info("Stopping AIOKafkaProducer")
            await self.producer.stop()
            self.producer = None

    async def send_event(self, topic: str, event_type: str, data: dict):
        """Sends an event to a Kafka topic with trace context propagation."""
        await self.start()
        with tracer.start_as_current_span(f"kafka_publish:{topic}") as span:
            payload = {
                "event_type": event_type,
                "data": data
            }
            span.set_attribute("kafka.topic", topic)
            span.set_attribute("kafka.event_type", event_type)
            
            # Inject trace context into headers
            headers = []
            carrier = {}
            TraceContextTextMapPropagator().inject(carrier)
            for k, v in carrier.items():
                headers.append((k, v.encode("utf-8")))

            logger.info("Publishing event %s to topic %s", event_type, topic)
            await self.producer.send_and_wait(
                topic,
                value=payload,
                headers=headers
            )

# Singleton producer manager instance
producer_manager = KafkaProducerManager()
