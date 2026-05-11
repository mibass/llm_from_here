import logging
import tempfile
import unittest

from llm_from_here.run_logging import (
    AGENT_TRACE_LOGGER_NAME,
    bootstrap_showrunner_logging,
    configure_show_run_logging,
    log_pydantic_agent_trace,
)


def _clear_handlers(logger: logging.Logger) -> None:
    for h in list(logger.handlers):
        logger.removeHandler(h)
        try:
            h.close()
        except OSError:
            pass


class TestRunLogging(unittest.TestCase):
    def tearDown(self) -> None:
        root = logging.getLogger()
        _clear_handlers(root)
        setattr(root, "_llmfh_logging_bootstrapped", False)
        _clear_handlers(logging.getLogger(AGENT_TRACE_LOGGER_NAME))

    def test_configure_writes_per_run_files(self) -> None:
        bootstrap_showrunner_logging()
        with tempfile.TemporaryDirectory() as tmp:
            configure_show_run_logging(tmp)
            logging.getLogger("llm_from_here.test").info("hello main")
            logging.getLogger(AGENT_TRACE_LOGGER_NAME).info("hello trace")
            main_path = f"{tmp}/show_runner.log"
            trace_path = f"{tmp}/agent_trace.log"
            with open(main_path, encoding="utf-8") as f:
                self.assertIn("hello main", f.read())
            with open(trace_path, encoding="utf-8") as f:
                self.assertIn("hello trace", f.read())

    def test_agent_trace_skips_when_unconfigured(self) -> None:
        setattr(logging.getLogger(), "_llmfh_logging_bootstrapped", False)
        _clear_handlers(logging.getLogger())
        bootstrap_showrunner_logging()

        class _DummyRunResult:
            run_id = "test-run"

            def new_messages_json(self) -> bytes:
                return b"[]"

        log_pydantic_agent_trace("scope", _DummyRunResult())


if __name__ == "__main__":
    unittest.main()
