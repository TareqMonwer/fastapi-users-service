from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    LOGGER_NAME: str = "fastapi-users-service"
    LOGGER_PATH: str = "logs/app.log"

    class Config:
        env_file = ".env"


settings = Settings()
