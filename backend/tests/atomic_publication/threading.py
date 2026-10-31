"""Bounded worker orchestration; exceptions always return to the parent test."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from django.db import close_old_connections, connections


@contextmanager
def workers():
    executor = ThreadPoolExecutor(max_workers=2)
    futures = []

    def submit(operation):
        def run():
            close_old_connections()
            try:
                return operation()
            finally:
                connections.close_all()
        future = executor.submit(run)
        futures.append(future)
        return future

    try:
        yield submit
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        for future in futures:
            assert future.done(), "Storage worker did not terminate"
