import json
import logging
import os
import shutil
import tempfile
import threading
from datetime import datetime
from pathlib import Path

import config
from core.models import Project
from core.serializer import project_from_dict, project_to_dict

logger = logging.getLogger(__name__)

# Global lock to prevent concurrent saves from corrupting JSON files.
# The InkCore extractor runs in a background thread and may trigger a
# bank save while the autosave timer fires on the main thread.
_save_lock = threading.Lock()


def _atomic_write_json(path: Path, data) -> None:
    """Write *data* as JSON to *path* atomically.

    Writes to a sibling .tmp file in the same directory (so the final
    os.replace() is guaranteed to be atomic on Linux) then renames it.
    This prevents a half-written file if the process is killed mid-write.
    Also keeps a single .bak copy of the previous file for emergency recovery.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # Keep one .bak before overwriting
        if path.exists():
            bak = path.with_suffix(".bak")
            try:
                shutil.copy2(path, bak)
            except OSError as e:
                logger.warning(f"Could not create backup {bak}: {e}")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class ProjectManager:
    def __init__(self):
        self.projects_dir = config.PROJECTS_DIR
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def list_projects(self) -> list[Project]:
        projects = []
        for f in sorted(self.projects_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                proj = self.load(f.stem)
                if proj:
                    projects.append(proj)
            except Exception as e:
                logger.warning(f"Could not load project {f}: {e}")
        return projects

    def save(self, project: Project) -> Path:
        project.touch()
        path = self.projects_dir / f"{project.id}.json"
        with _save_lock:
            _atomic_write_json(path, project_to_dict(project))
        logger.info(f"Saved project {project.name} to {path}")
        return path

    def load(self, project_id: str) -> Project | None:
        path = self.projects_dir / f"{project_id}.json"
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Corrupt JSON in {path}: {e}. Trying .bak fallback.")
            bak = path.with_suffix(".bak")
            if bak.exists():
                try:
                    with open(bak, encoding="utf-8") as f:
                        data = json.load(f)
                    logger.info(f"Loaded from backup {bak}")
                except Exception as e2:
                    logger.error(f"Backup also corrupt {bak}: {e2}")
                    return None
            else:
                return None
        except Exception as e:
            logger.error(f"Could not read {path}: {e}")
            return None
        return project_from_dict(data)

    def delete(self, project_id: str):
        path = self.projects_dir / f"{project_id}.json"
        if path.exists():
            # Remove image files referenced by ImageElements to avoid orphans
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                for page in data.get("pages", []):
                    for el in page.get("elements", []):
                        if el.get("element_type") == "image":
                            img_path = Path(el.get("image_path", ""))
                            if img_path.exists():
                                try:
                                    img_path.unlink()
                                    logger.debug(f"Removed orphan image {img_path}")
                                except OSError as e:
                                    logger.warning(f"Could not remove image {img_path}: {e}")
            except Exception as e:
                logger.warning(f"Could not clean up images for {project_id}: {e}")
            path.unlink(missing_ok=True)
            # Remove .bak as well
            bak = path.with_suffix(".bak")
            bak.unlink(missing_ok=True)
            logger.info(f"Deleted project {project_id}")

    def autosave(self, project: Project):
        config.AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
        path = config.AUTOSAVE_DIR / f"{project.id}_autosave.json"
        with _save_lock:
            _atomic_write_json(path, project_to_dict(project))

    def backup(self, project: Project):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = config.DATA_DIR / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        src = self.projects_dir / f"{project.id}.json"
        if src.exists():
            dst = backup_dir / f"{project.id}_{ts}.json"
            shutil.copy2(src, dst)
            self._rotate_backups(backup_dir, project.id, keep=5)

    def _rotate_backups(self, backup_dir: Path, project_id: str, keep: int):
        backups = sorted(backup_dir.glob(f"{project_id}_*.json"), key=lambda p: p.stat().st_mtime)
        while len(backups) > keep:
            try:
                backups.pop(0).unlink(missing_ok=True)
            except OSError as e:
                logger.warning(f"Could not remove old backup: {e}")
