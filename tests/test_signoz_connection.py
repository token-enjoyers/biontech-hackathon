"""
Connectivity test for SigNoz via raw gRPC OTLP.

Run with:
    hack26/bin/pip install grpcio opentelemetry-proto
    SIGNOZ_HOST=host:4317 PYTHONPATH=src hack26/bin/python3 tests/test_signoz_connection.py
"""

import os
import time

import grpc
import pytest

from opentelemetry.proto.collector.logs.v1 import logs_service_pb2
from opentelemetry.proto.collector.logs.v1 import logs_service_pb2_grpc
from opentelemetry.proto.common.v1 import common_pb2
from opentelemetry.proto.logs.v1 import logs_pb2
from opentelemetry.proto.resource.v1 import resource_pb2

SIGNOZ_HOST = os.getenv("SIGNOZ_HOST")


def test_grpc_log_export() -> None:
    if not SIGNOZ_HOST:
        pytest.skip("Set SIGNOZ_HOST to run the live SigNoz connectivity test.")

    channel = grpc.insecure_channel(SIGNOZ_HOST)
    stub = logs_service_pb2_grpc.LogsServiceStub(channel)

    now_ns = time.time_ns()

    request = logs_service_pb2.ExportLogsServiceRequest(
        resource_logs=[
            logs_pb2.ResourceLogs(
                resource=resource_pb2.Resource(
                    attributes=[
                        common_pb2.KeyValue(
                            key="service.name",
                            value=common_pb2.AnyValue(string_value="medical-wizard-mcp"),
                        )
                    ]
                ),
                scope_logs=[
                    logs_pb2.ScopeLogs(
                        log_records=[
                            logs_pb2.LogRecord(
                                time_unix_nano=now_ns,
                                observed_time_unix_nano=now_ns,
                                severity_number=logs_pb2.SeverityNumber.SEVERITY_NUMBER_INFO,
                                severity_text="INFO",
                                body=common_pb2.AnyValue(
                                    string_value="[GXP AUDIT] SigNoz connection test from medical-wizard-mcp"
                                ),
                                attributes=[
                                    common_pb2.KeyValue(
                                        key="tool",
                                        value=common_pb2.AnyValue(string_value="connection_test"),
                                    ),
                                    common_pb2.KeyValue(
                                        key="status",
                                        value=common_pb2.AnyValue(string_value="success"),
                                    ),
                                ],
                            )
                        ]
                    )
                ],
            )
        ]
    )

    response = stub.Export(request, timeout=10)
    print(f"✓ Log sent to SigNoz at {SIGNOZ_HOST}")
    print(f"  Response: {response}")
    channel.close()


if __name__ == "__main__":
    test_grpc_log_export()
