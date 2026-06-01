"""Pydantic request bodies for the OWUI-compat facade.

Only the small bodies the facade fully owns are modelled here. The chat
completions body is read as a raw dict in the handler (OWUI sends a large,
loosely-typed OpenAI payload — see ``translate.owui_body_to_proxy``).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class OwuiSigninBody(BaseModel):
    email: str
    password: str


class OwuiSignupBody(BaseModel):
    name: str
    email: str
    password: str
    profile_image_url: Optional[str] = None


class OwuiChatNewBody(BaseModel):
    chat: Dict[str, Any] = Field(default_factory=dict)
    folder_id: Optional[str] = None


class OwuiChatUpdateBody(BaseModel):
    chat: Dict[str, Any] = Field(default_factory=dict)
