"""
Роутер для управления правилами автоответа
"""
from fastapi import APIRouter, HTTPException, status, Query
from typing import List
import logging
from asyncpg.exceptions import UniqueViolationError

from .db import get_db_connection
from .schemas import RuleCreate, RuleUpdate, RuleResponse, PeerResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rules", tags=["Auto-reply Rules"])
peers_router = APIRouter(prefix="/peers", tags=["Peers"])

# MVP: фиксированный account_id = 1
DEFAULT_ACCOUNT_ID = 1


# ==================== RULES ====================

@router.get("/", response_model=List[RuleResponse])
async def get_all_rules(
    account_id: int = Query(
        default=DEFAULT_ACCOUNT_ID,
        description="Account ID (в MVP используется 1)"
    )
):
    """
    Получить список всех правил автоответа для указанного аккаунта.
    
    **Примечание**: peer_id — это внутренний ID из таблицы peers, 
    а не Telegram tg_peer_id (user_id).
    """
    try:
        async with get_db_connection() as conn:
            rows = await conn.fetch("""
                SELECT id, account_id, peer_id, enabled, template, min_interval_sec, created_at
                FROM auto_reply_rules
                WHERE account_id = $1
                ORDER BY created_at DESC
            """, account_id)
            
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Failed to get rules for account_id={account_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


@router.get("/{peer_id}", response_model=RuleResponse)
async def get_rule(
    peer_id: int,
    account_id: int = Query(
        default=DEFAULT_ACCOUNT_ID,
        description="Account ID (в MVP используется 1)"
    )
):
    """Получить правило по peer_id для указанного аккаунта."""
    try:
        async with get_db_connection() as conn:
            row = await conn.fetchrow("""
                SELECT id, account_id, peer_id, enabled, template, min_interval_sec, created_at
                FROM auto_reply_rules
                WHERE account_id = $1 AND peer_id = $2
            """, account_id, peer_id)
            
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Rule for account_id={account_id}, peer_id={peer_id} not found"
                )
            
            return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get rule for account_id={account_id}, peer_id={peer_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


@router.post("/", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rule(rule: RuleCreate):
    """
    Создать новое правило автоответа.
    
    **MVP ограничение**: Принимается только account_id = 1.
    """
    if rule.account_id != DEFAULT_ACCOUNT_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only account_id={DEFAULT_ACCOUNT_ID} is allowed in MVP version"
        )
    
    try:
        async with get_db_connection() as conn:
            # Проверяем, существует ли peer
            peer_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM peers WHERE id = $1)",
                rule.peer_id
            )
            if not peer_exists:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Peer with id={rule.peer_id} does not exist"
                )
            
            row = await conn.fetchrow("""
                INSERT INTO auto_reply_rules (account_id, peer_id, enabled, template, min_interval_sec)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id, account_id, peer_id, enabled, template, min_interval_sec, created_at
            """, rule.account_id, rule.peer_id, rule.enabled, rule.template, rule.min_interval_sec)
            
            logger.info(f"Created rule id={row['id']} for peer_id={rule.peer_id}")
            return dict(row)
    except UniqueViolationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rule for account_id={rule.account_id} and peer_id={rule.peer_id} already exists"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create rule: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


@router.put("/{peer_id}", response_model=RuleResponse)
async def update_rule(
    peer_id: int,
    rule: RuleUpdate,
    account_id: int = Query(default=DEFAULT_ACCOUNT_ID)
):
    """Обновить существующее правило. Обновляются только переданные поля."""
    try:
        update_fields = []
        values = []
        param_count = 1
        
        if rule.enabled is not None:
            update_fields.append(f"enabled = ${param_count}")
            values.append(rule.enabled)
            param_count += 1
        
        if rule.template is not None:
            update_fields.append(f"template = ${param_count}")
            values.append(rule.template)
            param_count += 1
        
        if rule.min_interval_sec is not None:
            update_fields.append(f"min_interval_sec = ${param_count}")
            values.append(rule.min_interval_sec)
            param_count += 1
        
        if not update_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update"
            )
        
        values.extend([account_id, peer_id])
        
        query = f"""
            UPDATE auto_reply_rules
            SET {', '.join(update_fields)}
            WHERE account_id = ${param_count} AND peer_id = ${param_count + 1}
            RETURNING id, account_id, peer_id, enabled, template, min_interval_sec, created_at
        """
        
        async with get_db_connection() as conn:
            row = await conn.fetchrow(query, *values)
            
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Rule for account_id={account_id}, peer_id={peer_id} not found"
                )
            
            logger.info(f"Updated rule for peer_id={peer_id}")
            return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update rule: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


@router.delete("/{peer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    peer_id: int,
    account_id: int = Query(default=DEFAULT_ACCOUNT_ID)
):
    """Удалить правило автоответа."""
    try:
        async with get_db_connection() as conn:
            result = await conn.execute("""
                DELETE FROM auto_reply_rules
                WHERE account_id = $1 AND peer_id = $2
            """, account_id, peer_id)
            
            if result == "DELETE 0":
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Rule for account_id={account_id}, peer_id={peer_id} not found"
                )
            
            logger.info(f"Deleted rule for peer_id={peer_id}")
            return None
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete rule: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


# ==================== PEERS ====================

@peers_router.get("/", response_model=List[PeerResponse])
async def get_all_peers(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0)
):
    """Получить список всех peers (собеседников)."""
    try:
        async with get_db_connection() as conn:
            rows = await conn.fetch("""
                SELECT id, tg_peer_id, username, first_name, last_name, is_bot, created_at
                FROM peers
                WHERE is_bot = false
                ORDER BY updated_at DESC
                LIMIT $1 OFFSET $2
            """, limit, offset)
            
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Failed to get peers: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


@peers_router.get("/by-tg-id/{tg_peer_id}", response_model=PeerResponse)
async def get_peer_by_tg_id(tg_peer_id: int):
    """Получить peer по Telegram user_id."""
    try:
        async with get_db_connection() as conn:
            row = await conn.fetchrow("""
                SELECT id, tg_peer_id, username, first_name, last_name, is_bot, created_at
                FROM peers
                WHERE tg_peer_id = $1
            """, tg_peer_id)
            
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Peer with tg_peer_id={tg_peer_id} not found"
                )
            
            return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get peer by tg_id: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )
