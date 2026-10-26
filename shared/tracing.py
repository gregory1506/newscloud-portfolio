"""Cloud Trace setup shared by every Cloud Function.

Only exports to Cloud Trace when running on Cloud Run / Cloud Functions gen2
(signalled by the ``K_SERVICE`` env var). Locally and in tests, spans are created
but never exported, so no network calls or background export threads happen
outside GCP.
"""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_initialized = False


def _running_on_cloud_run() -> bool:
    return bool(os.environ.get("K_SERVICE"))


def get_tracer(service_name: str) -> trace.Tracer:
    """Return a tracer for ``service_name``, configuring export once per process."""
    global _initialized
    if not _initialized:
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        if _running_on_cloud_run():
            from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

            project_id = os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
            provider.add_span_processor(
                BatchSpanProcessor(CloudTraceSpanExporter(project_id=project_id))
            )
        trace.set_tracer_provider(provider)
        _initialized = True
    return trace.get_tracer(service_name)
