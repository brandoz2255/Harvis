
import os
import shutil
import logging
import json
import requests
from typing import Optional, List, Dict, Any
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class VoiceModelInfo:
    name: str
    file_size_mb: float
    epochs: int
    tags: List[str]
    index_path: Optional[str] = None
    model_path: str = ""

# Dictionary of popular/preset models for easy downloading
POPULAR_MODELS = {
    "spongebob": {
        "url": "https://huggingface.co/links/spongebob-rvc-v2/resolve/main/spongebob.zip",
        "tags": ["cartoon", "character"]
    },
    "plankton": {
        "url": "https://huggingface.co/links/plankton-rvc-v2/resolve/main/plankton.zip",
        "tags": ["cartoon", "character"]
    },
    # Add more as needed
}

class VoiceModelManager:
    """
    Manages downloading, storing, and retrieving RVC voice models.
    """
    def __init__(self, models_dir: str = "voice_models"):
        self.models_dir = Path(models_dir)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.models_dir / "metadata.json"
        self.models_cache: Dict[str, VoiceModelInfo] = {}
        self._load_metadata()

    def _load_metadata(self):
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r') as f:
                    data = json.load(f)
                    for name, info in data.items():
                        self.models_cache[name] = VoiceModelInfo(**info)
            except Exception as e:
                logger.error(f"Failed to load voice model metadata: {e}")

    def _save_metadata(self):
        try:
            data = {name: info.__dict__ for name, info in self.models_cache.items()}
            with open(self.metadata_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save voice model metadata: {e}")

    def list_models(self, tag: Optional[str] = None) -> List[VoiceModelInfo]:
        if tag:
            return [m for m in self.models_cache.values() if tag in m.tags]
        return list(self.models_cache.values())

    def get_model_path(self, name: str) -> Optional[str]:
        if name in self.models_cache:
            model_info = self.models_cache[name]
            # Check if file actually exists
            path = Path(model_info.model_path)
            if path.exists():
                return str(path)
        return None
    
    def get_index_path(self, name: str) -> Optional[str]:
        if name in self.models_cache:
            model_info = self.models_cache[name]
            if model_info.index_path:
                path = Path(model_info.index_path)
                if path.exists():
                    return str(path)
        return None

    def download_model(self, url: str, name: Optional[str] = None, tags: Optional[List[str]] = None) -> Optional[VoiceModelInfo]:
        """
        Downloads a ZIP file containing an RVC model (.pth) and optionally an index file (.index).
        """
        import zipfile
        import io

        if name is None:
            name = url.split("/")[-1].replace(".zip", "")
        
        target_dir = self.models_dir / name
        if target_dir.exists():
            logger.info(f"Model {name} already exists.")
            if name in self.models_cache:
                return self.models_cache[name]
        
        target_dir.mkdir(exist_ok=True)
        
        try:
            logger.info(f"Downloading voice model from {url}...")
            response = requests.get(url, stream=True)
            response.raise_for_status()
            
            # Read zip content
            z = zipfile.ZipFile(io.BytesIO(response.content))
            z.extractall(target_dir)
            
            # Find .pth and .index files
            pth_files = list(target_dir.glob("*.pth"))
            index_files = list(target_dir.glob("*.index"))
            
            if not pth_files:
                logger.error(f"No .pth file found in downloaded archive for {name}")
                shutil.rmtree(target_dir)
                return None
            
            model_path = str(pth_files[0])
            index_path = str(index_files[0]) if index_files else None
            
            # Estimate metadata (mocking epoch/size for now)
            file_stats = pth_files[0].stat()
            size_mb = round(file_stats.st_size / (1024 * 1024), 2)
            
            info = VoiceModelInfo(
                name=name,
                file_size_mb=size_mb,
                epochs=0, # Unknown from just file
                tags=tags or ["downloaded"],
                model_path=model_path,
                index_path=index_path
            )
            
            self.models_cache[name] = info
            self._save_metadata()
            logger.info(f"Successfully installed voice model: {name}")
            return info
            
        except Exception as e:
            logger.error(f"Failed to download/install model {name}: {e}")
            if target_dir.exists():
                shutil.rmtree(target_dir)
            return None

    def delete_model(self, name: str) -> bool:
        if name in self.models_cache:
            target_dir = self.models_dir / name
            if target_dir.exists():
                shutil.rmtree(target_dir)
            del self.models_cache[name]
            self._save_metadata()
            return True
        return False

def download_popular_model(name: str, manager: VoiceModelManager) -> Optional[VoiceModelInfo]:
    if name not in POPULAR_MODELS:
        return None
    
    cfg = POPULAR_MODELS[name]
    return manager.download_model(cfg["url"], name=name, tags=cfg["tags"])
