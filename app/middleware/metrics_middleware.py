import time
from prometheus_client import Counter, Histogram, Gauge
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total number of HTTP requests",
    ["method", "endpoint", "status"],
)

REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
)

ACTIVE_REQUESTS = Gauge(
    "http_active_requests_total", "Total number of active HTTP requests"
)


class MetricsMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request, call_next):
        # Increment active requests
        ACTIVE_REQUESTS.inc()

        # Record start time
        start_time = time.time()

        # Get endpoint name (simplified)
        endpoint = request.url.path

        try:
            # Process request
            response = await call_next(request)

            # Record request duration
            duration = time.time() - start_time
            REQUEST_DURATION.labels(
                method=request.method, endpoint=endpoint
            ).observe(duration)

            # Record request count
            REQUEST_COUNT.labels(
                method=request.method,
                endpoint=endpoint,
                status=response.status_code,
            ).inc()

            return response

        except Exception as _:  # noqa
            # Record failed request
            duration = time.time() - start_time
            REQUEST_DURATION.labels(
                method=request.method, endpoint=endpoint
            ).observe(duration)

            REQUEST_COUNT.labels(
                method=request.method, endpoint=endpoint, status=500
            ).inc()

            raise
        finally:
            # Decrement active requests
            ACTIVE_REQUESTS.dec()
