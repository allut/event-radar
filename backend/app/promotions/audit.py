"""System audit rows for Promotion changes nobody triggered by hand (the sweep
and the Stripe webhook). The row rides the caller's transaction."""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.log_events import LOG_EVENT_ADMIN_ACTION
from app.models.audit import AdminAction
from app.models.promotions import Promotion

log = logging.getLogger(__name__)


def record_system_action(
    db: AsyncSession, promotion: Promotion, action: str, **extra: Any
) -> None:
    result = {
        "actor": "system",
        "status": promotion.status,
        "event_id": promotion.event_id,
        **extra,
    }
    db.add(AdminAction(action=action, target=str(promotion.id), result=result))
    log.info(
        "admin action: %s",
        action,
        extra={
            "event": LOG_EVENT_ADMIN_ACTION,
            "action": action,
            "target": promotion.id,
            "result": result,
        },
    )
