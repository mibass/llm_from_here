import os
import dotenv
dotenv.load_dotenv()

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

def get_env():
    return os.getenv('LLMFH_ENV', 'dev')

def is_production():
    return get_env() == 'prod'

def is_production_prefix():
    if is_production():
        return ''
    elif os.getenv('LLMFH_ENV', '') != '':
        return f"{os.getenv('LLMFH_ENV')}_"
    else:
        return 'dev_'