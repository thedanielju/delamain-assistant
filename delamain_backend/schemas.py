from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ContextMode = Literal["normal", "blank_slate"]
RunStatus = Literal[
    "queued",
    "running",
    "waiting_approval",
    "completed",
    "failed",
    "interrupted",
    "cancelled",
]


class ConversationCreate(BaseModel):
    title: str | None = None
    context_mode: ContextMode = "normal"
    model_route: str | None = None
    incognito_route: bool = False
    folder_id: str | None = None


class ConversationUpdate(BaseModel):
    title: str | None = None
    archived: bool | None = None
    folder_id: str | None = None


class PromptSubmit(BaseModel):
    content: str = Field(min_length=1)
    context_mode: ContextMode | None = None
    model_route: str | None = None
    incognito_route: bool | None = None


class PromptSubmitResponse(BaseModel):
    message_id: str
    run_id: str
    status: RunStatus


class ActionExecuteRequest(BaseModel):
    conversation_id: str | None = None


class SettingsPatch(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    conversation_id: str | None = None


class ToolSettingPatch(BaseModel):
    enabled: bool | None = None
    approval_policy: str | None = None
    conversation_id: str | None = None


class SyncthingConflictResolveRequest(BaseModel):
    path: str
    action: Literal["keep_canonical", "keep_conflict", "keep_both", "stage_review"]
    note: str | None = None


class ContextFilePatch(BaseModel):
    content: str
    conversation_id: str | None = None


class FolderCreate(BaseModel):
    name: str = Field(min_length=1)
    parent_id: str | None = None


class FolderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    parent_id: str | None = None


class PermissionResolve(BaseModel):
    decision: str
    note: str | None = None
    resolver: str | None = None


class ConversationOut(BaseModel):
    id: str
    title: str | None
    context_mode: str
    model_route: str | None
    incognito_route: bool
    sensitive_unlocked: bool
    folder_id: str | None = None
    archived: bool
    created_at: str
    updated_at: str


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    run_id: str | None
    role: str
    content: str
    status: str
    created_at: str
    updated_at: str


class RunOut(BaseModel):
    id: str
    conversation_id: str
    user_message_id: str
    assistant_message_id: str | None
    status: str
    context_mode: str
    model_route: str
    incognito_route: bool
    error_code: str | None
    error_message: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None


class HealthOut(BaseModel):
    status: str
    sqlite: dict[str, Any]
    litellm: dict[str, Any]
    config: dict[str, Any]
    budget: dict[str, Any] | None = None
    helpers: dict[str, Any]
