"""
Pydantic-модели для валидации запросов/ответов
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class RuleBase(BaseModel):
    """Базовая модель правила"""
    enabled: bool = True
    template: str = Field(..., min_length=1, max_length=4096)
    min_interval_sec: int = Field(default=3600, ge=0)


class RuleCreate(RuleBase):
    """Модель для создания правила"""
    account_id: int = Field(..., gt=0)
    peer_id: int = Field(..., gt=0)


class RuleUpdate(BaseModel):
    """
    Модель для обновления правила.
    Все поля опциональны - обновляются только переданные.
    """
    enabled: Optional[bool] = None
    template: Optional[str] = Field(None, min_length=1, max_length=4096)
    min_interval_sec: Optional[int] = Field(None, ge=0)


class RuleResponse(BaseModel):
    """Модель ответа с правилом"""
    id: int
    account_id: int
    peer_id: int
    enabled: bool
    template: str
    min_interval_sec: int
    created_at: datetime


class PeerResponse(BaseModel):
    """Модель ответа с информацией о peer"""
    id: int
    tg_peer_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    is_bot: bool
    created_at: datetime
