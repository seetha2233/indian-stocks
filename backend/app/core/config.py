from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    APP_NAME: str = "Indian AI Stock Intelligence"

    DATABASE_URL: str = (
        "postgresql+psycopg2://postgres:postgres@localhost:5432/stock_ai"
    )

    REDIS_URL: str = "redis://localhost:6379"

    # Which stocks the pipeline covers: "nse" (all NSE main-board equities)
    # or "nifty100"
    UNIVERSE: str = "nse"

    # LLM features (news sentiment, explanations, research chat) are
    # skipped when no key is set
    OPENAI_API_KEY: str | None = None

    OPENAI_MODEL: str = "gpt-5.4-mini"

    # Origins allowed to call the API (the React dev server)
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )


settings = Settings()