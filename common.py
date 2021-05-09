import logging
import sys

logger = logging.getLogger("Cartoonizer")
logger.propagate = False
log_lvl = {"debug": logging.DEBUG, "info": logging.INFO,
           "warning": logging.WARNING, "error": logging.ERROR,
           "critical": logging.CRITICAL}
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
stdhandler = logging.StreamHandler(sys.stdout)
stdhandler.setFormatter(formatter)
logger.addHandler(stdhandler)
