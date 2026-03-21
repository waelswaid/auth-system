from pydantic import BaseModel, EmailStr, Field
from typing import Literal


class ChangeRoleRequest(BaseModel):
    role: Literal["user", "admin"]


class DisableUserRequest(BaseModel):
    is_disabled: bool


class InviteUserRequest(BaseModel):
    email: EmailStr


class AcceptInviteRequest(BaseModel):
    code: str
    first_name: str = Field(min_length=1, max_length=255)
    last_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
