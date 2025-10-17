import logging
import sys
from pathlib import Path

from loguru import logger

# Remove default handler
logger.remove()


# Configure Loguru with a format that separates module name from message
def add_module_name(record):
    """Ensure every record has module_name in extra."""
    if "module_name" not in record["extra"]:
        record["extra"]["module_name"] = f"{record['name']}:{record['line']}"
    return True


logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <5}</level> | <cyan>{extra[module_name]}</cyan> - {message}",
    level="INFO",
    colorize=True,
    filter=add_module_name,
)


# Intercept standard logging
class InterceptHandler(logging.Handler):
    def emit(self, record):
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Get the module name correctly
        if record.name == "root":
            module_name = record.module
        elif "." in record.name:
            module_name = record.name  # Use full path for properly named loggers
        else:
            module_path = Path(record.pathname)
            module_name = module_path.stem  # Get filename without extension

        # Include line number in module name
        module_with_line = f"{module_name}:{record.lineno}"

        # Log using the extra parameter for module name to ensure proper coloring
        logger.bind(module_name=module_with_line).log(level, record.getMessage())


# Make sure all loguru logs include module_name
# This is to properly handle direct calls to logger.info() etc.
def patching_logger(orig_func, level_or_message, *args, **kwargs):
    # Get the caller's frame - we need to go up 2 frames to get past the lambda
    frame = sys._getframe(2)
    module_name = frame.f_globals.get("__name__", "")
    filename = frame.f_code.co_filename
    lineno = frame.f_lineno

    if not module_name:
        # Extract module name from filename if __name__ is not available
        module_name = Path(filename).stem

    # Format it like "module_name:lineno"
    module_with_line = f"{module_name}:{lineno}"

    # Bind the module_name to the logger
    bound_logger = logger.bind(module_name=module_with_line)

    # Now call the original function with the bound logger
    # This fixes issues with string formatting in messages with braces
    if level_or_message in [
        "TRACE",
        "DEBUG",
        "INFO",
        "SUCCESS",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ]:
        # Case for logger.log(level, message, *args, **kwargs)
        return bound_logger.log(level_or_message, *args, **kwargs)
    else:
        # Case for logger.info(message, *args, **kwargs), etc.
        return bound_logger.log("INFO", level_or_message, *args, **kwargs)


# Patch logger.log directly
original_log = logger.log
logger.log = lambda level, message, *args, **kwargs: patching_logger(
    original_log, level, message, *args, **kwargs
)

# Create new wrappers for each level that call the patched log function
logger.trace = lambda message, *args, **kwargs: logger.log(
    "TRACE", message, *args, **kwargs
)
logger.debug = lambda message, *args, **kwargs: logger.log(
    "DEBUG", message, *args, **kwargs
)
logger.info = lambda message, *args, **kwargs: logger.log(
    "INFO", message, *args, **kwargs
)
logger.success = lambda message, *args, **kwargs: logger.log(
    "SUCCESS", message, *args, **kwargs
)
logger.warning = lambda message, *args, **kwargs: logger.log(
    "WARNING", message, *args, **kwargs
)
logger.error = lambda message, *args, **kwargs: logger.log(
    "ERROR", message, *args, **kwargs
)
logger.critical = lambda message, *args, **kwargs: logger.log(
    "CRITICAL", message, *args, **kwargs
)

# Configure standard logging to use Loguru
logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

# Set specific logging levels for certain modules
# Set APScheduler's executors to ERROR level to suppress misfire warnings
logging.getLogger("apscheduler.executors.default").setLevel(logging.ERROR)
# Set APScheduler's scheduler to WARNING level to suppress job addition messages
logging.getLogger("apscheduler.scheduler").setLevel(logging.WARNING)

# Replace all existing loggers with Loguru
for name in logging.root.manager.loggerDict.keys():
    # Don't reset our specifically configured loggers
    if name not in ["apscheduler.executors.default", "apscheduler.scheduler"]:
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
