import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import sqlite3

try:
    from googleapiclient.errors import HttpError
except ImportError:
    class HttpError(Exception):
        pass

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Define what to retry on (Network errors, DB locks)
RETRY_EXCEPTIONS = (HttpError, sqlite3.OperationalError, TimeoutError)

# The Decorator
def robust_call():
    return retry(
        stop=stop_after_attempt(3),              # Try 3 times
        wait=wait_exponential(multiplier=1, min=2, max=10), # Wait 2s, 4s, 8s...
        retry=retry_if_exception_type(RETRY_EXCEPTIONS),
        reraise=True
    )

def safe_execute(func, *args, **kwargs):
    """Executes a function and catches errors gracefully."""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.error(f"CRITICAL FAILURE in {func.__name__}: {e}")
        return f"SYSTEM_ERROR: {str(e)}"
