import os
import logging
from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("syncops.telemetry")

def init_telemetry(app, service_name: str = "syncops-backend"):
    """Bootstraps OpenTelemetry tracing and metrics for the FastAPI app."""
    resource = Resource.create(attributes={
        "service.name": service_name,
        "environment": "development"
    })

    # Set tracer provider
    tracer_provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(tracer_provider)

    # Read OTLP endpoints from env
    otlp_endpoint_grpc = os.getenv("OTEL_EXPORTER_OTLP_GRPC_ENDPOINT", "http://localhost:4317")
    otlp_endpoint_http = os.getenv("OTEL_EXPORTER_OTLP_HTTP_ENDPOINT", "http://localhost:4318")

    trace_exporter = None
    metric_exporter = None

    # Try importing gRPC exporters
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as GRPCSpanExporter
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter as GRPCMetricExporter
        
        logger.info("Initializing OpenTelemetry using gRPC exporters at %s", otlp_endpoint_grpc)
        trace_exporter = GRPCSpanExporter(endpoint=otlp_endpoint_grpc, insecure=True)
        metric_exporter = GRPCMetricExporter(endpoint=otlp_endpoint_grpc, insecure=True)
    except Exception as e:
        logger.warning("Failed to initialize gRPC exporters (%s). Falling back to HTTP OTLP.", e)
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HTTPSpanExporter
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter as HTTPMetricExporter
            
            trace_url = f"{otlp_endpoint_http}/v1/traces"
            metric_url = f"{otlp_endpoint_http}/v1/metrics"
            logger.info("Initializing OpenTelemetry using HTTP exporters at %s / %s", trace_url, metric_url)
            trace_exporter = HTTPSpanExporter(endpoint=trace_url)
            metric_exporter = HTTPMetricExporter(endpoint=metric_url)
        except Exception as ex:
            logger.error("Failed to initialize HTTP exporters as well (%s). Telemetry is disabled.", ex)
            return None, None

    if trace_exporter and metric_exporter:
        # Add Span Processor for Tracing
        span_processor = BatchSpanProcessor(trace_exporter)
        tracer_provider.add_span_processor(span_processor)

        # Add Metric Reader for Metrics
        reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=5000)
        meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
        metrics.set_meter_provider(meter_provider)

        # Instrument FastAPI Application
        FastAPIInstrumentor.instrument_app(app)
        logger.info("OpenTelemetry instrumentation configured successfully.")
        
        return tracer_provider, meter_provider

    return None, None
