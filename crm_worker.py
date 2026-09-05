"""Durable scheduler process for production deployments."""
import os
import signal
import time

from crm_security import company_context, company_ids
from pipecat_server import run_jobs_now


running = True


def stop(*_args):
    global running
    running = False


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    interval = max(15, int(os.environ.get("SCHEDULER_INTERVAL_SECONDS", "60")))
    while running:
        started = time.monotonic()
        for company_id in company_ids():
            token = company_context.set(company_id)
            try:
                run_jobs_now()
            except Exception as exc:
                print(f"scheduler company={company_id} failed: {exc}", flush=True)
            finally:
                company_context.reset(token)
        remaining = interval - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(remaining)


if __name__ == "__main__":
    main()
