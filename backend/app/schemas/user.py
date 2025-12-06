"""User Pydantic schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserBase(BaseModel):
    """Base user schema."""

    spotify_id: str
    display_name: str | None = None
    email: str | None = None


class UserCreate(UserBase):
    """Schema for creating a user."""

    access_token: str
    refresh_token: str
    token_expires_at: datetime


class UserResponse(UserBase):
    """Schema for user API response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class TokenInfo(BaseModel):
    """Schema for token information (used internally)."""

    access_token: str
    refresh_token: str
    expires_at: datetime
