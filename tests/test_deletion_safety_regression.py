import unittest
import tempfile
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add backend to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from skills.files import FileOperationsSkill, DeleteFileSkill, send_to_recycle_bin


class TestDeletionSafetyRegression(unittest.IsolatedAsyncioTestCase):
    """
    Regression test suite for deletion safety:
    - A failed Trash operation MUST NOT fall back to permanent deletion (file remains on disk).
    - A failed Trash operation on a directory MUST NOT fall back to shutil.rmtree.
    - A successful Trash operation reports success correctly.
    - Explicit permanent deletion only occurs when 'permanent=True' is provided.
    """

    async def asyncSetUp(self):
        self.skill = FileOperationsSkill()
        self.temp_dir_obj = tempfile.TemporaryDirectory(prefix="bytex_test_del_safety_")
        self.temp_dir = Path(self.temp_dir_obj.name)

    async def asyncTearDown(self):
        try:
            self.temp_dir_obj.cleanup()
        except Exception:
            pass

    async def test_01_failed_trash_does_not_permanently_delete_file(self):
        """Proves a failed Trash operation does NOT delete a file via os.remove."""
        test_file = self.temp_dir / "critical_data.txt"
        test_file.write_text("irreplaceable content", encoding="utf-8")
        self.assertTrue(test_file.exists())

        # Mock send_to_recycle_bin to simulate failure (e.g. Finder error / no permissions)
        with patch("skills.files.send_to_recycle_bin", return_value=False):
            res = await self.skill.execute({
                "operation": "delete_file",
                "target_path": str(test_file),
                "confirmed": True
            })

            # Must report explicit failure
            self.assertFalse(res.success, "Result must report failure when moving to Trash fails")
            self.assertFalse(res.verified)
            self.assertEqual(res.error, "TrashOperationFailed")
            self.assertIn("preserved on disk", res.message)

            # CRITICAL: File MUST still exist on disk!
            self.assertTrue(test_file.exists(), "File must NOT be permanently removed when Trash fails!")
            self.assertEqual(test_file.read_text(encoding="utf-8"), "irreplaceable content")

    async def test_02_failed_trash_does_not_permanently_delete_directory(self):
        """Proves a failed Trash operation on a directory does NOT call shutil.rmtree."""
        sub_dir = self.temp_dir / "important_folder"
        sub_dir.mkdir(parents=True)
        nested_file = sub_dir / "nested.cpp"
        nested_file.write_text("int main() { return 0; }", encoding="utf-8")
        self.assertTrue(sub_dir.exists())
        self.assertTrue(nested_file.exists())

        with patch("skills.files.send_to_recycle_bin", return_value=False):
            res = await self.skill.execute({
                "operation": "delete_file",
                "target_path": str(sub_dir),
                "confirmed": True
            })

            self.assertFalse(res.success)
            self.assertFalse(res.verified)
            self.assertEqual(res.error, "TrashOperationFailed")
            self.assertIn("preserved on disk", res.message)

            # CRITICAL: Directory and nested files MUST still exist on disk!
            self.assertTrue(sub_dir.exists(), "Directory must NOT be deleted when Trash fails!")
            self.assertTrue(nested_file.exists(), "Nested file must NOT be deleted when Trash fails!")

    async def test_03_successful_trash_reports_success_correctly(self):
        """Proves a successful Trash operation reports success correctly."""
        test_file = self.temp_dir / "to_be_trashed.txt"
        test_file.write_text("temporary content", encoding="utf-8")

        # Simulate successful Trash by moving/unlinking in mock
        def mock_trash(p: Path) -> bool:
            if p.exists():
                p.unlink()
                return True
            return False

        with patch("skills.files.send_to_recycle_bin", side_effect=mock_trash):
            res = await self.skill.execute({
                "operation": "delete_file",
                "target_path": str(test_file),
                "confirmed": True
            })

            self.assertTrue(res.success)
            self.assertTrue(res.verified)
            self.assertFalse(test_file.exists())
            self.assertIn("deleted successfully", res.message)

    async def test_04_explicit_permanent_delete_only_when_authorized(self):
        """Proves permanent deletion only occurs when 'permanent=True' is explicitly supplied."""
        test_file = self.temp_dir / "permanent_target.txt"
        test_file.write_text("to permanently delete", encoding="utf-8")

        # With permanent=True, it permanently removes the file without Trash
        with patch("skills.files.send_to_recycle_bin") as mock_trash:
            res = await self.skill.execute({
                "operation": "delete_file",
                "target_path": str(test_file),
                "confirmed": True,
                "permanent": True
            })

            self.assertTrue(res.success)
            self.assertTrue(res.verified)
            self.assertFalse(test_file.exists())
            # send_to_recycle_bin should NOT even be called when explicitly permanent
            mock_trash.assert_not_called()

    async def test_05_delete_file_skill_wrapper_preserves_safety(self):
        """Proves DeleteFileSkill wrapper delegates safely."""
        skill = DeleteFileSkill()
        self.assertEqual(skill.name, "delete_file")
        self.assertIn("permanent", skill.parameters["properties"])

        test_file = self.temp_dir / "wrapped_test.txt"
        test_file.write_text("wrapped content", encoding="utf-8")

        with patch("skills.files.send_to_recycle_bin", return_value=False):
            res = await skill.execute({
                "target_path": str(test_file),
                "confirmed": True
            })
            self.assertFalse(res.success)
            self.assertTrue(test_file.exists(), "File must be preserved when Trash fails!")


if __name__ == "__main__":
    unittest.main()
