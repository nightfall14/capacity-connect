"""Pydantic contracts for JSON and WebSocket payloads."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class RegistrationModel(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    email: str
    phone: str = ""
    password: str = Field(min_length=6, max_length=128)
    confirm_password: str

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("Please provide a valid email address.")
        return value.lower()


class LoginModel(BaseModel):
    email: str
    password: str


class ChatMessageModel(BaseModel):
    room_type: Literal["global", "private"] = "global"
    body: str = Field(min_length=1, max_length=2000)
    recipient_id: int | None = None
    anonymous: bool = False
    is_anonymous: bool = False  # alias used by chat route


class CourseStatusModel(BaseModel):
    status: Literal["Registered", "In Progress", "Completed"]
