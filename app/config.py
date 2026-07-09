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
