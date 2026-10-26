import os
import psutil
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, Union

class ActionVerifier:
    """
    Unified Action Verification Layer for ByteX PC Control.
    Verifies actual physical Windows / filesystem state before reporting success.
    """

    @classmethod
    def verify_file_creation(cls, path: Union[Path, str]) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        p = Path(path)
        exists = p.exists()
        is_file = p.is_file() if exists else False
        size = p.stat().st_size if (exists and is_file) else 0

        verified = exists and is_file
        v_data = {"exists": exists, "is_file": is_file, "size_bytes": size, "path": str(p)}

        if not verified:
            err = f"File creation verification failed: File '{p}' does not exist on disk as a regular file."
            return False, v_data, err

        return True, v_data, None

    @classmethod
    def verify_folder_creation(cls, path: Union[Path, str]) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        p = Path(path)
        exists = p.exists()
        is_dir = p.is_dir() if exists else False

        verified = exists and is_dir
        v_data = {"exists": exists, "is_dir": is_dir, "path": str(p)}

        if not verified:
            err = f"Folder creation verification failed: Directory '{p}' does not exist on disk."
            return False, v_data, err

        return True, v_data, None

    @classmethod
    def verify_rename(cls, old_path: Union[Path, str], new_path: Union[Path, str]) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        old_p = Path(old_path)
        new_p = Path(new_path)

        old_exists = old_p.exists()
        new_exists = new_p.exists()

        verified = (not old_exists) and new_exists
        v_data = {
            "old_path": str(old_p),
            "old_path_exists": old_exists,
            "new_path": str(new_p),
            "new_path_exists": new_exists
        }

        if not verified:
            if old_exists and not new_exists:
                err = f"Rename verification failed: Old path '{old_p}' still exists and new path '{new_p}' does not exist."
            elif old_exists and new_exists:
                err = f"Rename verification failed: Both old path '{old_p}' and new path '{new_p}' exist."
            else:
                err = f"Rename verification failed: New path '{new_p}' was not created."
            return False, v_data, err

        return True, v_data, None

    @classmethod
    def verify_copy(cls, source_path: Union[Path, str], destination_path: Union[Path, str]) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        src_p = Path(source_path)
        dst_p = Path(destination_path)

        src_exists = src_p.exists()
        dst_exists = dst_p.exists()

        verified = src_exists and dst_exists
        v_data = {
            "source_path": str(src_p),
            "source_exists": src_exists,
            "destination_path": str(dst_p),
            "destination_exists": dst_exists
        }

        if not verified:
            err = f"Copy verification failed: Destination '{dst_p}' does not exist after copy operation."
            return False, v_data, err

        return True, v_data, None

    @classmethod
    def verify_move(cls, source_path: Union[Path, str], destination_path: Union[Path, str]) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        src_p = Path(source_path)
        dst_p = Path(destination_path)

        src_exists = src_p.exists()
        dst_exists = dst_p.exists()

        verified = (not src_exists) and dst_exists
        v_data = {
            "source_path": str(src_p),
            "source_exists": src_exists,
            "destination_path": str(dst_p),
            "destination_exists": dst_exists
        }

        if not verified:
            if src_exists:
                err = f"Move verification failed: Source '{src_p}' still exists after move."
            else:
                err = f"Move verification failed: Destination '{dst_p}' does not exist after move."
            return False, v_data, err

        return True, v_data, None

    @classmethod
    def verify_delete(cls, path: Union[Path, str]) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        p = Path(path)
        exists_after = p.exists()

        verified = not exists_after
        v_data = {"path": str(p), "exists_after": exists_after}

        if not verified:
            err = f"Deletion verification failed: Target '{p}' still exists on disk after deletion attempt."
            return False, v_data, err

        return True, v_data, None

    @classmethod
    def verify_process_running(cls, process_keyword: str) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        kw = process_keyword.lower().strip()
        matched_pids = []
        for p in psutil.process_iter(['pid', 'name']):
            try:
                name = p.info['name']
                if name and (kw in name.lower() or name.lower().startswith(kw)):
                    matched_pids.append(p.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        running = len(matched_pids) > 0
        v_data = {"process": process_keyword, "running": running, "pids": matched_pids}
        if not running:
            return False, v_data, f"Process verification failed: '{process_keyword}' is not running."
        return True, v_data, None

verifier = ActionVerifier()
