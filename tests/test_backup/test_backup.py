"""Tests for backup and recovery."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from thumbelina.backup.manager import BackupManager


@pytest.fixture
def backup_dir():
    """Create a temporary directory for backups."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def manager(backup_dir):
    """Create a BackupManager."""
    return BackupManager(backup_dir=backup_dir)


class TestBackupManager:
    """Tests for the BackupManager class."""

    def test_manager_class_exists(self):
        """BackupManager should be importable."""
        assert BackupManager is not None

    def test_manager_creates_instance(self, backup_dir):
        """Should create a BackupManager."""
        m = BackupManager(backup_dir=backup_dir)
        assert m is not None

    @pytest.mark.asyncio
    async def test_create_backup(self, manager):
        """Should create a backup."""
        result = await manager.create_backup(
            name="test-backup",
            data={"key": "value"},
        )

        assert result is not None
        assert result.name == "test-backup"

    @pytest.mark.asyncio
    async def test_list_backups(self, manager):
        """Should list backups."""
        await manager.create_backup(name="backup-1", data={"a": 1})
        await manager.create_backup(name="backup-2", data={"b": 2})

        backups = await manager.list_backups()
        assert len(backups) == 2

    @pytest.mark.asyncio
    async def test_list_empty(self, manager):
        """Should return empty list when no backups."""
        backups = await manager.list_backups()
        assert backups == []

    @pytest.mark.asyncio
    async def test_restore_backup(self, manager):
        """Should restore a backup."""
        await manager.create_backup(name="backup-1", data={"key": "value"})

        backups = await manager.list_backups()
        data = await manager.restore_backup(backups[0].id)

        assert data == {"key": "value"}

    @pytest.mark.asyncio
    async def test_restore_nonexistent(self, manager):
        """Should return None for non-existent backup."""
        data = await manager.restore_backup("00000000-0000-0000-0000-000000000000")
        assert data is None

    @pytest.mark.asyncio
    async def test_delete_backup(self, manager):
        """Should delete a backup."""
        await manager.create_backup(name="backup-1", data={"a": 1})

        backups = await manager.list_backups()
        result = await manager.delete_backup(backups[0].id)

        assert result is True
        assert len(await manager.list_backups()) == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, manager):
        """Should return False when deleting non-existent backup."""
        result = await manager.delete_backup("00000000-0000-0000-0000-000000000000")
        assert result is False

    @pytest.mark.asyncio
    async def test_backup_persists_data(self, backup_dir):
        """Backup should persist data to disk."""
        manager1 = BackupManager(backup_dir=backup_dir)
        await manager1.create_backup(name="persistent", data={"test": 123})

        # Create new manager with same directory
        manager2 = BackupManager(backup_dir=backup_dir)
        backups = await manager2.list_backups()

        assert len(backups) == 1
        data = await manager2.restore_backup(backups[0].id)
        assert data == {"test": 123}

    @pytest.mark.asyncio
    async def test_restore_invalid_id_raises(self, manager):
        """Should raise ValueError for invalid backup ID."""
        with pytest.raises(ValueError, match="Invalid backup ID format"):
            await manager.restore_backup("../etc/passwd")

    @pytest.mark.asyncio
    async def test_delete_invalid_id_raises(self, manager):
        """Should raise ValueError for invalid backup ID."""
        with pytest.raises(ValueError, match="Invalid backup ID format"):
            await manager.delete_backup("../../secret")

    @pytest.mark.asyncio
    async def test_restore_rejects_dot_dot(self, manager):
        """Should reject path traversal attempts."""
        with pytest.raises(ValueError, match="Invalid backup ID format"):
            await manager.restore_backup("../../../etc/passwd")

    @pytest.mark.asyncio
    async def test_list_backups_preserves_name(self, manager):
        """Listed backups should preserve the original name."""
        await manager.create_backup(name="my-backup", data={"key": "value"})

        backups = await manager.list_backups()
        assert len(backups) == 1
        assert backups[0].name == "my-backup"

    @pytest.mark.asyncio
    async def test_restore_backward_compatible(self, backup_dir):
        """Should restore old-format backups (plain JSON without envelope)."""
        # Write an old-format backup directly
        import uuid
        backup_id = str(uuid.uuid4())
        filepath = os.path.join(backup_dir, f"{backup_id}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump({"legacy_key": "legacy_value"}, f)

        manager = BackupManager(backup_dir=backup_dir)
        data = await manager.restore_backup(backup_id)
        assert data == {"legacy_key": "legacy_value"}
