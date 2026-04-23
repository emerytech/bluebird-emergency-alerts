import logging


def configure_logging(level: str) -> None:
    """
    Keep logging simple and production-friendly.
    Uvicorn will also configure handlers, but this ensures our modules behave consistently.
    """

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
