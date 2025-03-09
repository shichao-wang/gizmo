from .client import ApiClient


def api_client(cookie_string: str) -> ApiClient:
    return ApiClient(cookie_string)
