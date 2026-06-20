import time
import logging
from datetime import datetime
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError, OperationalError

logger = logging.getLogger(__name__)


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            start_time = time.time()
            response = await call_next(request)
            process_time = time.time() - start_time
            response.headers["X-Process-Time"] = str(process_time)
            return response
        except HTTPException as he:
            logger.warning(f"HTTP Exception: {he.detail}")
            return JSONResponse(
                status_code=he.status_code,
                content={
                    "error": he.detail,
                    "status_code": he.status_code,
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
        except IntegrityError as ie:
            logger.error(f"Database Integrity Error: {str(ie)}")
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "error": "Database conflict occurred",
                    "detail": "A unique constraint was violated",
                    "status_code": status.HTTP_409_CONFLICT,
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
        except OperationalError as oe:
            logger.error(f"Database Operational Error: {str(oe)}")
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "error": "Database service unavailable",
                    "status_code": status.HTTP_503_SERVICE_UNAVAILABLE,
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
        except Exception as e:
            logger.error(f"Unhandled Exception: {str(e)}", exc_info=True)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error": "Internal server error",
                    "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                    "timestamp": datetime.utcnow().isoformat()
                }
            )


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        client_ip = request.client.host if request.client else "unknown"
        method = request.method
        path = request.url.path

        logger.info(
            f"Request started: {method} {path} "
            f"from {client_ip}"
        )

        try:
            response = await call_next(request)
            process_time = time.time() - start_time
            status_code = response.status_code

            logger.info(
                f"Request completed: {method} {path} "
                f"Status: {status_code} "
                f"Duration: {process_time:.4f}s"
            )

            return response
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(
                f"Request failed: {method} {path} "
                f"Error: {str(e)} "
                f"Duration: {process_time:.4f}s",
                exc_info=True
            )
            raise


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.request_counts = {}

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        minute_key = int(now // 60)

        if client_ip not in self.request_counts:
            self.request_counts[client_ip] = {}

        if minute_key not in self.request_counts[client_ip]:
            self.request_counts[client_ip] = {minute_key: 0}

        self.request_counts[client_ip][minute_key] += 1

        if self.request_counts[client_ip][minute_key] > self.requests_per_minute:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Rate limit exceeded",
                    "detail": f"Maximum {self.requests_per_minute} requests per minute allowed",
                    "status_code": status.HTTP_429_TOO_MANY_REQUESTS,
                    "timestamp": datetime.utcnow().isoformat()
                }
            )

        return await call_next(request)
