"""Validated HTTP request models."""
from typing import Annotated, Literal
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
    options: list[TaskOption] = Field(default_factory=list, max_length=8)
    mode: Literal['single', 'multiple', 'confirm', 'input'] = 'single'
    allow_custom: bool | None = None
    min_choices: int = Field(default=1, ge=1, le=8)
    max_choices: int | None = Field(default=None, ge=1, le=8)
    input_hint: str = Field(default='', max_length=200)
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
        if self.allow_custom is None:
            self.allow_custom = self.mode != 'confirm'
        if self.mode == 'input':
            if self.options or not self.allow_custom:
                raise ValueError('Input cards require text and no options')
        elif not 2 <= len(self.options) <= (4 if self.mode == 'confirm' else 8):
            raise ValueError('Choice cards require 2-8 options; confirm allows 2-4')
        if len({option.id for option in self.options}) != len(self.options):
            raise ValueError('Option IDs must be distinct')
        if self.mode != 'multiple' and sum(option.recommended for option in self.options) > 1:
            raise ValueError('Only one recommended option is allowed')
        if self.mode == 'multiple':
            self.max_choices = self.max_choices if self.max_choices is not None else len(self.options)
            if not self.min_choices <= self.max_choices <= len(self.options):
                raise ValueError('Choice limits must fit the options')
        elif self.min_choices != 1 or self.max_choices is not None:
            raise ValueError('Choice limits only apply to multiple cards')
        if self.mode != 'input' and self.input_hint:
            raise ValueError('Input hint only applies to input cards')
        return self

    def definition(self):
        # Preserve the 1.11 single-card fingerprint so old dedup-key retries still match.
        value = self.model_dump(include={'title', 'prompt', 'options', 'allow_custom', 'expires_in'})
        if self.mode != 'single':
            value['mode'] = self.mode
        if self.mode == 'multiple':
            value.update(min_choices=self.min_choices, max_choices=self.max_choices)
        if self.mode == 'input':
            value['input_hint'] = self.input_hint
        return value


class TaskAnswer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{16,80}$')
    choice_id: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9_-]{1,32}$')
    choice_ids: list[Annotated[str, Field(pattern=r'^[a-zA-Z0-9_-]{1,32}$')]] | None = Field(default=None, max_length=8)
    text: str = Field(default='', max_length=2000)


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['processing', 'completed', 'cancelled']
    result: str = Field(default='', max_length=4000)

