from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sys
from pathlib import Path
from prometheus_client import make_asgi_app

from app.database import engine
from app.models.base import Base
from app.routes import users as users_router
from app.middleware.logging_middleware import LoggingMiddleware
from app.middleware.metrics_middleware import MetricsMiddleware
from app.middleware.register_exceptions import RegisterExceptionsMiddleware
from app.utils.logger import setup_logger

# Create logs directory
logs_dir = Path("logs")
logs_dir.mkdir(exist_ok=True)

# Setup logging
logger = setup_logger(
    name="fastapi-users-service", log_level="INFO", log_file="logs/app.log"
)

# Create database tables
try:
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully")
except Exception as e:
    logger.error(f"Error creating database tables: {str(e)}")
    sys.exit(1)

# Create FastAPI app
app = FastAPI(
    title="FastAPI Users Service",
    description="A FastAPI service for managing users with CRUD operations",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

RegisterExceptionsMiddleware = RegisterExceptionsMiddleware(app)

# Add metrics middleware
app.add_middleware(MetricsMiddleware)

# Add logging middleware
app.add_middleware(LoggingMiddleware)

# Include routers
app.include_router(users_router.router, prefix="/api/v1")

# Add Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


# Health check endpoint
@app.get("/health")
async def health_check():
    """
    Health check endpoint
    """
    logger.info("Health check requested")
    return {
        "status": "healthy",
        "service": "FastAPI Users Service",
        "version": "1.0.0",
    }


# Root endpoint
@app.get("/")
async def root():
    """
    Root endpoint
    """
    logger.info("Root endpoint accessed")
    return {
        "message": "Welcome to FastAPI Users Service",
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics",
    }


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting FastAPI Users Service")
    uvicorn.run(
        "main:app", host="0.0.0.0", port=8000, reload=True, log_level="info"
    )
