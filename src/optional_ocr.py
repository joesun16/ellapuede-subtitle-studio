"""A failed optional check must not discard successful primary recognition."""
import threading


class OptionalOCR:
    def __init__(self, owner, label, factory):
        self.owner = owner
        self.label = label
        self.factory = factory
        self.pool = None
        self.failure = None
        self.lock = threading.RLock()

    def recognize(self, image, **settings):
        import resource_control as control
        try:
            with self.lock:
                if self.failure:
                    return None
                if self.pool is None:
                    self.pool = self.factory()
                pool = self.pool
                for name, value in settings.items():
                    setattr(pool, name, value)
            return pool.recognize(image)
        except (OSError, ImportError, RuntimeError, ValueError) as error:
            # Cancellation and MemoryError deliberately propagate.
            with self.lock:
                if not self.failure:
                    self.failure = f'{self.label}不可用，已跳过该项辅助检查，保留主识别结果：{error}'
                    warnings = getattr(self.owner, 'optional_warnings', None)
                    if warnings is None:
                        warnings = self.owner.optional_warnings = {}
                    warnings[self.label] = self.failure
                    control.emit('warning', message=self.failure)
            return None

    def close(self):
        if self.pool is not None:
            self.pool.close()
