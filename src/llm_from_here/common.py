import os

def get_resources_path():
    base_dir = os.path.dirname(__file__)
    return os.path.join(base_dir, 'resources')

def log_exception(logger_error_func):
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger_error_func(f"Exception occurred in {func.__name__}: {str(e)}")
                raise
        return wrapper
    return decorator

