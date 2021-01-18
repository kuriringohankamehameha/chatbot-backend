import logging
import os
import types
from functools import wraps

from channels.exceptions import AcceptConnection, DenyConnection, StopConsumer


def add_newlines(self: logging.Logger, num_newlines=1) -> None:
    """Add newlines to a logger object

    Args:
        num_newlines (int, optional): Number of new lines. Defaults to 1.
    """
    self.removeHandler(self.base_handler)
    self.addHandler(self.newline_handler)

    # Main code comes here
    for _ in range(num_newlines):
        self.info('')

    self.removeHandler(self.newline_handler)
    self.addHandler(self.base_handler)


def create_logger(app_name: str) -> logging.Logger:
    """Creates the logger for the current application

    Args:
        app_name (str): The name of the application

    Returns:
        logging.Logger: A logger object for that application
    """
    if not os.path.exists(os.path.join(os.getcwd(), 'logs')):
        os.mkdir(os.path.join(os.getcwd(), 'logs'))

    app_logfile = os.path.join(os.getcwd(), 'logs', f'{app_name}.log')

    logger = logging.getLogger(f"{app_name}-logger")
    logger.setLevel(logging.DEBUG)

    # handler = logging.FileHandler(filename=app_logfile, mode='a')
    handler = logging.handlers.RotatingFileHandler(filename=app_logfile, mode='a', maxBytes=5000, backupCount=5)
    handler.setLevel(logging.DEBUG)

    # Set the formatter
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    handler.setFormatter(formatter)

    logger.addHandler(handler)

    # Set it as the base handler
    logger.base_handler = handler

    # Also add a newline handler to switch to later
    newline_handler = logging.FileHandler(filename=app_logfile, mode='a')
    newline_handler.setLevel(logging.DEBUG)
    newline_handler.setFormatter(logging.Formatter(fmt='')) # Must be an empty format
    
    logger.newline_handler = newline_handler

    # Also add the provision for a newline handler using a custom method attribute
    logger.newline = types.MethodType(add_newlines, logger)

    # Also add a StreamHandler for printing to stderr
    console_handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    console_handler.setFormatter(formatter)
    
    logger.addHandler(console_handler)

    return logger


# Create the logger for the clientwidget app
logger = create_logger('clientwidget-updated')


class LiveChatException(Exception):
    """An Exception Class for sending Consumer specific Exceptions
    """
    def __init__(self, message, errors):
        # Call Exception.__init__(message)
        # to use the same Message header as the parent class
        super().__init__(message)
        self.errors = errors


def log_exceptions(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (AcceptConnection, DenyConnection, StopConsumer):
            raise
        except LiveChatException as livechatexception:
            logger.error(
                "LiveChatException (ERROR: {}) occured in {}:".format(livechatexception.errors, func.__qualname__),
                exc_info=livechatexception,
            )
            logger.newline()
            raise
        except Exception as exception:
            if not getattr(exception, "logged_by_wrapper", False):
                # print("Error: Unhandled Exception occured:")
                logger.error(
                    "Unhandled exception occurred in {}:".format(func.__qualname__),
                    exc_info=exception,
                )
                logger.newline()
                setattr(exception, "logged_by_wrapper", True)    
            raise
    return wrapper


def log_consumer_exceptions(ConsumerClass):
    for method_name, method in list(ConsumerClass.__dict__.items()):
        if callable(method) and not (method_name.startswith('__')):
            setattr(ConsumerClass, method_name, log_exceptions(method))
    return ConsumerClass
