from typing import Optional

from pydantic import BaseModel

from app.models import (
    InteractionMode,
    ProviderType,
)


class LLMModelCreate(BaseModel):
    name: str
    provider_type: ProviderType = ProviderType.OPENAI
    base_url: str
    api_key: str
    model: str = "gpt-4o-mini"


class LLMModelRead(BaseModel):
    id: int
    name: str
    provider_type: ProviderType
    base_url: str
    api_key_masked: str
    model: str
    created_at: str


class LLMModelUpdate(BaseModel):
    name: Optional[str] = None
    provider_type: Optional[ProviderType] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


class AgentConfigCreate(BaseModel):
    name: str
    git_repo_url: str
    git_ref: str = "main"
    git_access_token: Optional[str] = None
    dockerfile_path: str = "Dockerfile"
    env_example_path: Optional[str] = None
    api_port: Optional[int] = None
    entrypoint: Optional[list[str]] = None
    env_vars: dict[str, str] = {}
    resources: Optional[dict] = None
    interaction_mode: InteractionMode = InteractionMode.NONE
    api_config: Optional[dict] = None
    langgraph_config: Optional[dict] = None


class AgentConfigUpdate(BaseModel):
    name: Optional[str] = None
    git_repo_url: Optional[str] = None
    git_ref: Optional[str] = None
    git_access_token: Optional[str] = None
    dockerfile_path: Optional[str] = None
    env_example_path: Optional[str] = None
    api_port: Optional[int] = None
    entrypoint: Optional[list[str]] = None
    env_vars: Optional[dict[str, str]] = None
    resources: Optional[dict] = None
    interaction_mode: Optional[InteractionMode] = None
    api_config: Optional[dict] = None
    langgraph_config: Optional[dict] = None
