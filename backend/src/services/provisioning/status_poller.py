import asyncio
import logging

from sqlalchemy.orm import Session

from src.core.database import SessionLocal
from src.models.database_instance import DatabaseInstance, InstanceStatus
from src.services.auth import cleanup_expired_tokens
from src.services.instance import sync_connection_port
from src.services.provisioning.base import ProvisionerBase
from src.services.status_history import record_status_change
from src.services.provisioning.factory import get_provisioner
from src.services.provisioning.types import ProvisionerStatus

logger = logging.getLogger(__name__)

# Interval in seconds between each polling cycle
_POLL_INTERVAL_SECONDS = 30

# Expired token cleanup: every N poll cycles (30s × 2880 = 24h)
_TOKEN_CLEANUP_EVERY_N_CYCLES = 2880
_poll_cycle_counter = 0


def _reconcile_instance(
    db: Session, provisioner: ProvisionerBase, instance: DatabaseInstance
) -> None:
    """
    Reconciles the state of ONE instance with what Docker reports.

    Applied to instances that SHOULD be running (RUNNING and FAILED):

    - RUNNING container → ensures the published port matches the database
      (Docker republishes a new port when the container restarts after a
      host restart) and, if the instance was FAILED, auto-recovers it to RUNNING.
    - STOPPED container → exists but stopped (host/Docker restarted, OOM, crash).
      Tries to restart it; on success resyncs the port and returns to RUNNING; on
      failure marks it FAILED (and tries again on the next cycle).
    - NOT_FOUND/ERROR container → gone for good. If it was RUNNING marks it FAILED
      for the operator to investigate; if it was already FAILED leaves it as is (there's
      nothing to recover — re-provisioning would create an empty database).
    """
    infra_status = provisioner.get_status(instance.id)

    if infra_status == ProvisionerStatus.RUNNING:
        changed = False
        port = provisioner.get_port(instance.id)
        if port is not None and port != instance.port:
            sync_connection_port(instance, port)
            changed = True
        if instance.status != InstanceStatus.RUNNING:
            logger.info(
                "Instance %s recovered: container is running again", instance.id
            )
            record_status_change(db, instance, InstanceStatus.RUNNING)
            changed = True
        if changed:
            db.commit()

    elif infra_status == ProvisionerStatus.STOPPED:
        logger.warning(
            "Instance %s has a stopped container — attempting to restart", instance.id
        )
        try:
            new_port = provisioner.start(instance.id)
        except Exception as exc:
            logger.error("Failed to restart instance %s: %s", instance.id, exc)
            if instance.status != InstanceStatus.FAILED:
                record_status_change(db, instance, InstanceStatus.FAILED)
                db.commit()
            return
        sync_connection_port(instance, new_port)
        # The DB may already be RUNNING (container went down without the database knowing);
        # only record the transition if the status actually changed (avoids a redundant row).
        if instance.status != InstanceStatus.RUNNING:
            record_status_change(db, instance, InstanceStatus.RUNNING)
        db.commit()
        logger.info("Instance %s restarted successfully (port %d)", instance.id, new_port)

    else:  # NOT_FOUND or ERROR
        if instance.status == InstanceStatus.RUNNING:
            logger.warning(
                "Instance %s is RUNNING in the database but the container reports '%s' "
                "— marking as FAILED",
                instance.id,
                infra_status.value,
            )
            record_status_change(db, instance, InstanceStatus.FAILED)
            db.commit()


def poll_once() -> None:
    """
    Synchronous reconciliation of all instances that should be running.

    Why synchronous?
    This function is called via asyncio.to_thread() from the async loop, so it can
    do blocking operations (SQL queries + Docker API calls) without
    blocking the event loop that processes HTTP requests.

    Why SessionLocal() directly instead of get_db()?
    get_db() is a FastAPI generator designed to be used as Depends()
    inside an HTTP request's context. The poller runs outside that context
    (it's a background task), so it creates its own Session and closes it
    manually in the finally block.

    Which instances we reconcile:
    - RUNNING and FAILED → the desired state is "running", so we reconcile them
      (includes auto-recovering instances that went down in a Docker restart).
    - STOPPED → an intentional stop by the operator; we don't touch it.
    - DELETING/DELETED/PENDING/PROVISIONING → transient or final states
      managed by other flows; the poller ignores them.

    TokenBlacklist cleanup:
    - Every _TOKEN_CLEANUP_EVERY_N_CYCLES cycles (~24h), removes
      expired tokens from the blacklist. Expired tokens are invalid by definition
      (the JWT rejects them via 'exp'), so keeping them only wastes space.
    """
    global _poll_cycle_counter
    _poll_cycle_counter += 1

    provisioner = get_provisioner()
    db = SessionLocal()
    try:
        instances = (
            db.query(DatabaseInstance)
            .filter(
                DatabaseInstance.status.in_(
                    [InstanceStatus.RUNNING, InstanceStatus.FAILED]
                ),
                DatabaseInstance.deleted_at.is_(None),
            )
            .all()
        )

        for instance in instances:
            try:
                _reconcile_instance(db, provisioner, instance)
            except Exception as exc:
                db.rollback()
                logger.exception(
                    "Error reconciling instance %s: %s", instance.id, exc
                )

        # Periodic cleanup of expired tokens from the blacklist
        if _poll_cycle_counter % _TOKEN_CLEANUP_EVERY_N_CYCLES == 0:
            try:
                removed = cleanup_expired_tokens(db)
                if removed:
                    logger.info("TokenBlacklist cleanup: %d expired entries removed", removed)
            except Exception as exc:
                logger.warning("TokenBlacklist cleanup failed: %s", exc)

    finally:
        db.close()


async def status_polling_loop(stop_event: asyncio.Event) -> None:
    """
    Async loop that runs poll_once() every _POLL_INTERVAL_SECONDS.

    Clean shutdown via stop_event:
    Instead of abruptly cancelling the task (which could leave a Session
    open or a commit half-done), we use asyncio.wait_for(stop_event.wait()).
    When FastAPI's lifespan calls stop_event.set() on shutdown:
    - If it's waiting for the next cycle → wait_for returns immediately
    - The while checks stop_event.is_set() → exits the loop
    - The task ends gracefully

    poll_once() is synchronous (SQL + Docker API = blocking I/O).
    asyncio.to_thread() runs it in a thread pool, freeing the event loop to
    keep processing HTTP requests during polling.
    """
    logger.info(
        "Status poller started (interval: %ds)", _POLL_INTERVAL_SECONDS
    )

    while not stop_event.is_set():
        try:
            await asyncio.to_thread(poll_once)
        except Exception as exc:
            logger.exception("Error in polling cycle: %s", exc)

        # Wait for the interval OR the shutdown signal — whichever comes first
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=_POLL_INTERVAL_SECONDS,
            )
        except asyncio.TimeoutError:
            pass  # Normal — interval expired, next poll cycle

    logger.info("Status poller stopped")
