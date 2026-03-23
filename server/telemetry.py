"""OpenTelemetry setup for TTSQwen — traces + metrics + logs to OTel Collector."""

import logging

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from config import OTEL_ENDPOINT

SERVICE_NAME = "ttsqwen"

_logger_provider = None


def init_telemetry():
    """Initialize OTel tracer, meter, and logger providers. Call once at startup."""
    global _logger_provider
    resource = Resource.create({"service.name": SERVICE_NAME})

    # Traces
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{OTEL_ENDPOINT}/v1/traces"))
    )
    trace.set_tracer_provider(tracer_provider)

    # Metrics
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{OTEL_ENDPOINT}/v1/metrics"),
        export_interval_millis=15_000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    # Logs
    _logger_provider = LoggerProvider(resource=resource)
    _logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{OTEL_ENDPOINT}/v1/logs"))
    )
    set_logger_provider(_logger_provider)

    # Bridge Python logging → OTel
    otel_handler = LoggingHandler(level=logging.INFO, logger_provider=_logger_provider)
    logging.getLogger().addHandler(otel_handler)
    logging.getLogger().setLevel(logging.INFO)


def shutdown_telemetry():
    """Flush and shut down providers."""
    global _logger_provider
    tracer_provider = trace.get_tracer_provider()
    if hasattr(tracer_provider, "shutdown"):
        tracer_provider.shutdown()
    meter_provider = metrics.get_meter_provider()
    if hasattr(meter_provider, "shutdown"):
        meter_provider.shutdown()
    if _logger_provider:
        _logger_provider.shutdown()


# ─── Shared instruments ───

tracer = trace.get_tracer(SERVICE_NAME)
meter = metrics.get_meter(SERVICE_NAME)

# Counters
request_counter = meter.create_counter(
    "tts.requests",
    description="Total TTS requests",
    unit="1",
)
error_counter = meter.create_counter(
    "tts.errors",
    description="Total TTS errors",
    unit="1",
)

# Histograms
generate_duration = meter.create_histogram(
    "tts.generate.duration",
    description="TTS audio generation time",
    unit="s",
)
summarize_duration = meter.create_histogram(
    "tts.summarize.duration",
    description="Summarization time",
    unit="s",
)
audio_output_duration = meter.create_histogram(
    "tts.audio.duration",
    description="Generated audio duration",
    unit="s",
)
model_load_duration = meter.create_histogram(
    "tts.model_load.duration",
    description="Model load + warmup time",
    unit="s",
)
input_chars = meter.create_histogram(
    "tts.input.chars",
    description="Input text length in characters",
    unit="chars",
)
