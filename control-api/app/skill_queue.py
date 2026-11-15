"""Publish skill scans while the caller holds the scan row lock."""
import json

import pika


def publish(url: str, scan_id: int, started_at: str) -> None:
    params = pika.URLParameters(url)
    params.socket_timeout = 5
    params.stack_timeout = 10
    params.blocked_connection_timeout = 5
    with pika.BlockingConnection(params) as connection:
        channel = connection.channel()
        channel.queue_declare(queue="skill-scans", durable=True)
        channel.confirm_delivery()
        channel.basic_publish(
            exchange="", routing_key="skill-scans", mandatory=True,
            body=json.dumps({"scan_id": scan_id, "started_at": started_at}).encode(),
            properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
        )
