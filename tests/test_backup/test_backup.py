"""Tests for backup and recovery."""

from __future__ import annotations

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
        data = await manager.restore_backup("nonexistent")
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
        result = await manager.delete_backup("nonexistent")
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
