"""Multi-instance coordination for PRIMARY/READER roles.

This module handles coordination between multiple instances accessing the same database.
Only one instance (PRIMARY) should perform indexing operations at a time, while all
instances can perform read operations (search).
"""

import threading
import time
import uuid
from enum import Enum
from typing import TYPE_CHECKING

from obsidian_index.logger import logging

if TYPE_CHECKING:
    from obsidian_index.index.database_sqlite import Database

logger = logging.getLogger(__name__)


class Role(Enum):
    """Instance role for coordination."""

    AUTO = "auto"  # Coordinate via database
    PRIMARY = "primary"  # Always index, skip coordination
    READER = "reader"  # Never index, skip coordination


class Coordinator:
    """Coordinates PRIMARY/READER roles between multiple instances.

    The coordinator manages:
    - Unique instance ID generation
    - PRIMARY role claiming/releasing
    - Heartbeat loop for PRIMARY instances
    - Stale primary detection for READER instances
    """

    HEARTBEAT_INTERVAL = 5.0  # seconds
    STALE_THRESHOLD = 15.0  # seconds

    def __init__(self, database: "Database", role: Role = Role.AUTO):
        self.database = database
        self.configured_role = role
        self.instance_id = str(uuid.uuid4())
        self._is_primary = False
        self._heartbeat_thread: threading.Thread | None = None
        self._stop_heartbeat = threading.Event()
        self._lock = threading.Lock()

        logger.info(
            "Coordinator initialized with instance_id=%s, role=%s",
            self.instance_id[:8],
            role.value,
        )

    @property
    def is_primary(self) -> bool:
        """Check if this instance is currently the PRIMARY."""
        if self.configured_role == Role.PRIMARY:
            return True
        if self.configured_role == Role.READER:
            return False
        with self._lock:
            return self._is_primary

    def start(self):
        """Start the coordinator.

        For AUTO mode: attempts to claim PRIMARY role and starts heartbeat if successful.
        For PRIMARY mode: no coordination needed.
        For READER mode: no coordination needed.
        """
        if self.configured_role == Role.PRIMARY:
            logger.info("Running in PRIMARY mode (coordination disabled)")
            self._is_primary = True
            return

        if self.configured_role == Role.READER:
            logger.info("Running in READER mode (indexing disabled)")
            self._is_primary = False
            return

        # AUTO mode: try to claim primary
        self._try_claim_primary()

        if self._is_primary:
            self._start_heartbeat()

    def stop(self):
        """Stop the coordinator and release PRIMARY role if held."""
        self._stop_heartbeat.set()

        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=2.0)

        if self.configured_role == Role.AUTO and self._is_primary:
            try:
                self.database.release_primary(self.instance_id)
                logger.info("Released PRIMARY role")
            except Exception as e:
                logger.warning("Failed to release PRIMARY role: %s", e)

    def _try_claim_primary(self) -> bool:
        """Attempt to claim the PRIMARY role.

        Returns True if we successfully claimed PRIMARY.
        """
        current_time = time.time()

        with self._lock:
            if self.database.try_claim_primary(self.instance_id, current_time):
                self._is_primary = True
                logger.info("Claimed PRIMARY role")
                return True
            else:
                holder = self.database.get_primary_holder()
                if holder:
                    logger.info(
                        "Running as READER (PRIMARY held by %s, heartbeat %.1fs ago)",
                        holder[0][:8],
                        current_time - holder[1],
                    )
                else:
                    logger.info("Running as READER")
                return False

    def _start_heartbeat(self):
        """Start the heartbeat thread for PRIMARY instances."""
        self._stop_heartbeat.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="coordinator-heartbeat",
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self):
        """Background thread that updates heartbeat for PRIMARY instances."""
        while not self._stop_heartbeat.wait(self.HEARTBEAT_INTERVAL):
            try:
                current_time = time.time()
                if not self.database.update_heartbeat(self.instance_id, current_time):
                    # Lost primary role
                    with self._lock:
                        self._is_primary = False
                    logger.warning("Lost PRIMARY role (heartbeat update failed)")
                    break
            except Exception as e:
                logger.warning("Heartbeat failed: %s", e)

    def check_and_maybe_claim_primary(self) -> bool:
        """Check if primary is stale and try to claim if so.

        This is called by READER instances when they detect a file change.
        If the current PRIMARY is stale, the READER can attempt to become PRIMARY.

        Returns True if this instance should handle the indexing operation.
        """
        if self.configured_role == Role.PRIMARY:
            return True

        if self.configured_role == Role.READER:
            return False

        # AUTO mode
        with self._lock:
            if self._is_primary:
                return True

        # Check if primary is stale
        if self.database.is_primary_stale(self.STALE_THRESHOLD):
            logger.info("Primary appears stale, attempting to claim...")
            if self._try_claim_primary():
                self._start_heartbeat()
                return True

        return False

    def should_index(self) -> bool:
        """Check if this instance should perform indexing operations.

        Returns True if:
        - Role is PRIMARY (forced)
        - Role is AUTO and we're the primary
        """
        return self.is_primary
