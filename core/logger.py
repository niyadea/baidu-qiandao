"""日志器配置：sign.log 按天轮转，仅保留当天日志。"""

import logging
from logging.handlers import TimedRotatingFileHandler

from .paths import LOG_FILE

logger = logging.getLogger("tieba_sign")
logger.setLevel(logging.INFO)

if not logger.handlers:
    _file_handler = TimedRotatingFileHandler(
        LOG_FILE,
        when="midnight",
        interval=1,
        backupCount=0,
        encoding="utf-8",
        delay=True,
    )
    _file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s  [%(levelname)s]  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(_file_handler)
