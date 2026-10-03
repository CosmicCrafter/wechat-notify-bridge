"""Validated HTTP request models."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

class PairStart(BaseModel):
    model_config = ConfigDict(extra='forbid')
    replace: bool = False


class ClientName(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=32)


class PairSession(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: str = Field(min_length=1, max_length=100)


class PairVerify(PairSession):
    code: str = Field(pattern=r'^[0-9]{1,16}$')


class ConversationRegistration(BaseModel):
    model_config = ConfigDict(extra='forbid')
    conversation_key: str = Field(min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=20)


class ConversationState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    active: bool


class Message(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=20000)
    dedup_key: str = Field(min_length=1, max_length=200)
    dry_run: bool = False
    conversation_id: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator('text', 'dedup_key')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Must not be blank')
        return value


class Notice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    task: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=800)
    need_user: str = Field(min_length=1, max_length=800)
    dedup_key: str = Field(min_length=1, max_length=200)
    source: str = Field(default='Codex', min_length=1, max_length=80)
    level: Literal['info', 'warning', 'urgent'] = 'warning'
    dry_run: bool = False
    conversation_id: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator('task', 'reason', 'need_user', 'dedup_key', 'source')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Must not be blank')
        return value


