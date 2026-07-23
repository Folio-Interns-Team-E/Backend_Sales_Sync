from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # database
    database_url: str
    
    # jwt
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    
    # external apis
    grok_api_key: str = ""
    apollo_api_key: str = ""
    pinecone_api_key: str = ""
    pinecone_index_name: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_bucket_name: str = ""
    aws_region: str = ""

    cal_api_key: str = ""
    cal_event_type_id: str = ""

    google_client_id: str = ""
    google_client_secret: str = ""

    backend_url: str = "http://localhost:8000"

    # upstash redis
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""

    # stripe
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_growth_price: str = ""
    stripe_enterprise_price: str = ""

    RESEND_API_KEY: str = ""
    FROM_EMAIL: str = ""
    DB_ENCRYPTION_KEY: str = ""
    
    # app
    app_env: str = "development"
    frontend_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
            "https://frontend-vrdj.vercel.app",
        ]
    )
    
    class Config:
        env_file = (".env", "backend/.env")


settings = Settings()
