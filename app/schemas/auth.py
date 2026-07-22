from pydantic import BaseModel, EmailStr, field_validator
from uuid import UUID


def validate_bcrypt_password(password: str) -> str:
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Password cannot be longer than 72 bytes.")
    return password


class RegisterRequest(BaseModel):
    full_name: str
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_must_fit_bcrypt(cls, password: str) -> str:
        return validate_bcrypt_password(password)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_must_fit_bcrypt(cls, password: str) -> str:
        return validate_bcrypt_password(password)

class TokenResponse(BaseModel):
    access_token: str #jwt token
    token_type: str = "bearer"
    user_id: UUID #primary key
    full_name: str
    email: EmailStr

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    needs_verification: bool = False
    email: str | None = None
    access_token: str | None = None
    token_type: str = "bearer"
    user_id: UUID | None = None
    full_name: str | None = None


class RegisterResponse(BaseModel):
    user_id: UUID
    full_name: str
    email: str
    needs_verification: bool = True

    class Config:
        from_attributes = True


class OTPRequest(BaseModel):
    email: EmailStr

class OTPVerifyRequest(BaseModel):
    email: EmailStr
    otp: str