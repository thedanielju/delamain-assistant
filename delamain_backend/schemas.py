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
    selected_context_paths: list[str] | None = Field(default=None, max_length=12)


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


class VaultContextPinRequest(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=12)


class VaultContextPreviewRequest(BaseModel):
    prompt: str = ""
    context_mode: ContextMode | None = None
    paths: list[str] | None = Field(default=None, max_length=12)


class VaultPolicyExclusionCreate(BaseModel):
    pattern: str = Field(min_length=1, max_length=500)
    reason: str | None = Field(default=None, max_length=500)


class VaultFolderInitRequest(BaseModel):
    kind: Literal["project", "course", "reference"]
    name: str = Field(min_length=1, max_length=120)


class VaultMaintenanceProposalCreate(BaseModel):
    kind: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    paths: list[str] = Field(default_factory=list, max_length=50)
    payload: dict[str, Any] = Field(default_factory=dict)
    conversation_id: str | None = None


class VaultMaintenanceProposalUpdate(BaseModel):
    status: str | None = None
    title: str | None = Field(default=None, max_length=200)
    description: str | None = None
    paths: list[str] | None = Field(default=None, max_length=50)
    payload: dict[str, Any] | None = None


class VaultEnrichmentRunRequest(BaseModel):
    paths: list[str] | None = Field(default=None, max_length=12)
    limit: int = Field(default=4, ge=1, le=12)
    force: bool = False
    create_proposals: bool = True


class VaultRelationFeedbackRequest(BaseModel):
    from_path: str = Field(min_length=1, max_length=500)
    to_path: str = Field(min_length=1, max_length=500)
    relation_type: str = Field(default="related", min_length=1, max_length=80)
    decision: Literal["accepted", "rejected"]


class VaultEnrichmentBatchRequest(BaseModel):
    limit: int = Field(default=12, ge=1, le=48)
    force: bool = False
    create_proposals: bool = True


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
    system: dict[str, Any] | None = None
