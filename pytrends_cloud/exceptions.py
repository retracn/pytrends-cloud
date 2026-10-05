"""Same exception names as pytrends, so existing ``except`` blocks keep working."""


class ResponseError(Exception):
    """Something went wrong getting the data."""

    def __init__(self, message, response=None):
        super().__init__(message)
        self.response = response


class TooManyRequestsError(ResponseError):
    """Kept for compatibility with pytrends. The hosted service rotates IPs, so you shouldn't see it."""
