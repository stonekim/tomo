class PlatformError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


def missing():
    return PlatformError(404, 'NOT_FOUND', 'Resource not found')
