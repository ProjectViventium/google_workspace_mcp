import logging

from core.log_formatter import configure_sensitive_dependency_logging


def test_http_dependency_info_logs_are_suppressed() -> None:
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.INFO)

    configure_sensitive_dependency_logging()

    assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() == logging.WARNING
