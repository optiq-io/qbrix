from abc import ABC, abstractmethod
from functools import wraps


def register(method_name: str = None):
    def decorator(method):
        @wraps(method)
        def wrapper(self, *args, **kwargs):
            if method_name is None:
                start_invoker = f"on_{method.__name__}_start"
                end_invoker = f"on_{method.__name__}_end"
            else:
                start_invoker = f"on_{method_name}_start"
                end_invoker = f"on_{method_name}_end"
            if self.callbacks:
                for callback in self.callbacks:
                    if hasattr(callback, start_invoker):
                        getattr(callback, start_invoker)(self)
            result = method(self, *args, **kwargs)
            if self.callbacks:
                for callback in self.callbacks:
                    if hasattr(callback, end_invoker):
                        getattr(callback, end_invoker)(self)
            return result

        return wrapper

    return decorator


class BaseCallback(ABC):

    @property
    @abstractmethod
    def scope(self) -> str:
        pass

    def on_select_start(self, *args, **kwargs):
        pass

    def on_select_end(self, *args, **kwargs):
        pass

    def on_feed_start(self, *args, **kwargs):
        pass

    def on_feed_end(self, *args, **kwargs):
        pass
