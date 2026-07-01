from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # database
    database_url: str
    
    # jwt
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    
    # external apis
    grok_api_key: str
    apollo_api_key: str
    pinecone_api_key: str
    pinecone_index_name: str
    aws_access_key_id: str
    aws_secret_access_key: str
    aws_bucket_name: str
    aws_region: str
    
    # app
    app_env: str = "development"
    
    class Config:
        env_file = ".env"


settings = Settings()