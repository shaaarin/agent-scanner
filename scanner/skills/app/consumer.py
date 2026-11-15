"""Run one AMQP consumer per execution slot, keeping heartbeats alive during scans."""
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import httpx
import pika

from app import control_client, runner

log = logging.getLogger(__name__)


def process(body: bytes) -> None:
    message = json.loads(body)
    scan_id = message["scan_id"]
    started_at = message["started_at"]
    if type(scan_id) is not int or scan_id < 1 or not isinstance(started_at, str):
        raise ValueError("invalid scan_id")
    try:
        scan = control_client.get_scan(scan_id, wait_for_dispatch=True)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return
        raise
    if scan["type"] != runner.SCAN_TYPE or scan["status"] != "running":
        return
    # A later start can reuse the scan ID after a publishing transaction rolls back.
    if datetime.fromisoformat(scan["started_at"]).replace(tzinfo=None).isoformat() != started_at:
        return
    runner.run_scan(scan_id)
    # A temporary API failure can prevent the runner from saving its final state.
    if control_client.get_scan(scan_id)["status"] == "running":
        raise RuntimeError("scan has no saved result yet")


def consume(url: str, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            with pika.BlockingConnection(pika.URLParameters(url)) as conn, ThreadPoolExecutor(1) as pool:
                channel = conn.channel()
                channel.queue_declare(queue="skill-scans", durable=True)
                channel.basic_qos(prefetch_count=1)
                for method, _, body in channel.consume("skill-scans", inactivity_timeout=1):
                    if method:
                        future = pool.submit(process, body)
                        while not future.done():
                            conn.sleep(0.25)
                        try:
                            future.result()
                        except (KeyError, ValueError, TypeError):
                            log.exception("Invalid skill-scans message")
                            channel.basic_reject(method.delivery_tag, requeue=False)
                        else:
                            channel.basic_ack(method.delivery_tag)
                    if stop.is_set():
                        break
        except Exception:
            # Closing the channel requeues any delivery without an acknowledgement.
            log.exception("Skill queue connection or delivery failed")
            stop.wait(3)
