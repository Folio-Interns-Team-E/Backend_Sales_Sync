from pydantic import BaseModel, EmailStr
from uuid import UUID

class RegisterRequest(BaseModel):
    full_name: str
    email: EmailStr
    password: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str #jwt token
    token_type: str = "bearer"
    user_id: UUID #primary key
    full_name: str
    email: EmailStr

    #no clue what this is
    class Config:
        from_attributes = True