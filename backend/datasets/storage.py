"""Dataset storage management."""
import os
import uuid
import logging
from typing import Optional, List
from config import Config

logger = logging.getLogger(__name__)

class DatasetStorage:
    def __init__(self):
        self.upload_folder = Config.UPLOAD_FOLDER

    def save(self, file_obj, filename: str) -> str:
        if not os.path.exists(self.upload_folder):
            os.makedirs(self.upload_folder)
            
        file_path = os.path.join(self.upload_folder, filename)
        if os.path.exists(file_path):
            name, ext = os.path.splitext(filename)
            filename = f"{name}_{uuid.uuid4().hex}{ext}"
            file_path = os.path.join(self.upload_folder, filename)
            
        file_obj.save(file_path)
        logger.info(f"Saved file to {file_path}")
        return file_path

    def get_path(self, filename: str) -> Optional[str]:
        file_path = os.path.join(self.upload_folder, filename)
        if os.path.exists(file_path):
            return file_path
        return None

    def exists(self, filename: str) -> bool:
        return self.get_path(filename) is not None

    def delete(self, filename: str) -> bool:
        file_path = self.get_path(filename)
        if file_path:
            try:
                os.remove(file_path)
                logger.info(f"Deleted file {file_path}")
                return True
            except OSError as e:
                logger.error(f"Failed to delete {file_path}: {e}")
        return False

    def list_files(self) -> List[str]:
        if not os.path.exists(self.upload_folder):
            return []
        return [f for f in os.listdir(self.upload_folder) if os.path.isfile(os.path.join(self.upload_folder, f))]

dataset_storage = DatasetStorage()
