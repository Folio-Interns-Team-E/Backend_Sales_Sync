from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from uuid import UUID


def validate_bcrypt_password(password: str) -> str:
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Password cannot be longer than 72 bytes.")
    return password


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$")
    password: str = Field(min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def password_must_fit_bcrypt(cls, password: str) -> str:
        return validate_bcrypt_password(password)


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


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=120)
    company: str | None = Field(default=None, max_length=160)
    job_title: str | None = Field(default=None, max_length=120)

    @field_validator("full_name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value

    @field_validator("company", "job_title")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value is not None else None


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    full_name: str
    email: EmailStr
    company: str | None = None
    job_title: str | None = None

class TokenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    access_token: str #jwt token
    token_type: str = "bearer"
    user_id: UUID #primary key
    full_name: str
    email: EmailStr

class LoginResponse(BaseModel):
    needs_verification: bool = False
    needs_mfa: bool = False
    mfa_ticket: str | None = None
    email: str | None = None
    access_token: str | None = None
    token_type: str = "bearer"
    user_id: UUID | None = None
    full_name: str | None = None


class RegisterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    full_name: str
    email: str
    needs_verification: bool = True

class OTPRequest(BaseModel):
    email: EmailStr

class OTPVerifyRequest(BaseModel):
    email: EmailStr
    otp: str


class MfaCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class MfaLoginRequest(MfaCodeRequest):
    ticket: str = Field(min_length=32, max_length=128)


class MfaDisableRequest(MfaCodeRequest):
    password: str = Field(min_length=1, max_length=72)

    @field_validator("password")
    @classmethod
    def password_must_fit_bcrypt(cls, password: str) -> str:
        return validate_bcrypt_password(password)


class MfaStatusResponse(BaseModel):
    enabled: bool


class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str
    expires_in: int


class MfaRecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]
