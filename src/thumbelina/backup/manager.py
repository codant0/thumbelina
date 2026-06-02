"""Backup and recovery manager."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class BackupInfo:
    """Information about a backup."""

    id: str
    name: str
    created_at: datetime
    size_bytes: int = 0


class BackupManager:
    """Manager for creating and restoring backups.

    Parameters
    ----------
    backup_dir:
        Directory to store backups.
    """

    def __init__(self, backup_dir: str) -> None:
        self.backup_dir = backup_dir
        os.makedirs(backup_dir, exist_ok=True)

    async def create_backup(self, name: str, data: dict[str, Any]) -> BackupInfo:
        """Create a backup.

        Parameters
        ----------
        name:
            Name for the backup.
        data:
            Data to backup.

        Returns
        -------
        BackupInfo
            Information about the created backup.
        """
        backup_id = str(uuid.uuid4())
        filename = f"{backup_id}.json"
        filepath = os.path.join(self.backup_dir, filename)

        content = json.dumps(data, ensure_ascii=False, indent=2)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        return BackupInfo(
            id=backup_id,
            name=name,
            created_at=datetime.now(),
            size_bytes=len(content.encode("utf-8")),
        )

    async def list_backups(self) -> list[BackupInfo]:
        """List all backups."""
        backups = []
        for filename in os.listdir(self.backup_dir):
            if filename.endswith(".json"):
                filepath = os.path.join(self.backup_dir, filename)
                stat = os.stat(filepath)
                backup_id = filename.replace(".json", "")
                backups.append(BackupInfo(
                    id=backup_id,
                    name=backup_id,
                    created_at=datetime.fromtimestamp(stat.st_mtime),
                    size_bytes=stat.st_size,
                ))
        return sorted(backups, key=lambda b: b.created_at, reverse=True)

    async def restore_backup(self, backup_id: str) -> dict[str, Any] | None:
        """Restore a backup.

        Parameters
        ----------
        backup_id:
            ID of the backup to restore.

        Returns
        -------
        dict[str, Any] | None
            Restored data, or None if backup not found.
        """
        filepath = os.path.join(self.backup_dir, f"{backup_id}.json")
        if not os.path.exists(filepath):
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    async def delete_backup(self, backup_id: str) -> bool:
        """Delete a backup.

        Parameters
        ----------
        backup_id:
            ID of the backup to delete.

        Returns
        -------
        bool
            True if deleted, False if not found.
        """
        filepath = os.path.join(self.backup_dir, f"{backup_id}.json")
        if not os.path.exists(filepath):
            return False

        os.remove(filepath)
        return True
