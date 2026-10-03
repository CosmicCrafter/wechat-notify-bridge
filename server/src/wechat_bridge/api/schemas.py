"""Validated HTTP request models."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class TaskOption(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,32}$')
    label: str = Field(min_length=1, max_length=80)
    description: str = Field(default='', max_length=500)
    recommended: bool = False

    @field_validator('label')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Must not be blank')
        return value


class TaskCard(BaseModel):
    model_config = ConfigDict(extra='forbid')
    conversation_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    dedup_key: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=4000)
    options: list[TaskOption] = Field(min_length=2, max_length=8)
    allow_custom: bool = True
    expires_in: int = Field(default=86400, ge=60, le=604800)
    dry_run: bool = False

    @field_validator('title', 'prompt', 'dedup_key')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Must not be blank')
        return value

    @model_validator(mode='after')
    def distinct_options(self):
        if len({option.id for option in self.options}) != len(self.options):
            raise ValueError('Option IDs must be distinct')
        if sum(option.recommended for option in self.options) > 1:
            raise ValueError('Only one recommended option is allowed')
        return self


class TaskAnswer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{16,80}$')
    choice_id: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9_-]{1,32}$')
    text: str = Field(default='', max_length=2000)


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['processing', 'completed', 'cancelled']
    result: str = Field(default='', max_length=4000)


