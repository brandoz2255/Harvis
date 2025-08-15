"""Vibe Coding Models API Routes"""

from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional, Dict, Any
import logging
import requests
import os
from pydantic import BaseModel

# Import auth dependencies
from auth_utils import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/models", tags=["vibe-models"])

# Pydantic models for response
class ModelInfo(BaseModel):
    name: str
    displayName: str
    status: str = "available"  # available, loading, error, offline
    size: Optional[str] = None
    description: Optional[str] = None
    capabilities: List[str] = ["text-generation"]
    performance: Optional[Dict[str, Any]] = None

class ModelsResponse(BaseModel):
    models: List[ModelInfo]
    total: int
    ollama_status: str = "unknown"

@router.get("/available", response_model=ModelsResponse)
async def get_available_models(
    user: Dict = Depends(get_current_user)
):
    """Get all available AI models from Ollama"""
    try:
        ollama_url = os.getenv("OLLAMA_URL", "http://ollama:11434")
        models = []
        ollama_status = "offline"
        
        try:
            # Query Ollama for available models
            api_key = os.getenv("OLLAMA_API_KEY", "key")
            headers = {"Authorization": f"Bearer {api_key}"} if api_key != "key" else {}
            response = requests.get(f"{ollama_url}/api/tags", headers=headers, timeout=5)
            
            if response.status_code == 200:
                ollama_status = "online"
                data = response.json()
                ollama_models = data.get("models", [])
                
                for model_data in ollama_models:
                    # Extract model info
                    model_name = model_data.get("name", "unknown")
                    model_size = model_data.get("size", 0)
                    
                    # Format size in human readable format
                    size_str = None
                    if model_size:
                        if model_size > 1024**3:  # GB
                            size_str = f"{model_size / (1024**3):.1f}GB"
                        elif model_size > 1024**2:  # MB
                            size_str = f"{model_size / (1024**2):.0f}MB"
                        else:
                            size_str = f"{model_size}B"
                    
                    # Create display name
                    display_name = model_name.replace(":", " ").title()
                    if ":" in model_name:
                        base_name, version = model_name.split(":", 1)
                        display_name = f"{base_name.title()} ({version})"
                    
                    # Determine capabilities based on model name
                    capabilities = ["text-generation"]
                    if any(x in model_name.lower() for x in ["code", "coder", "programming"]):
                        capabilities.extend(["code-generation", "code-analysis"])
                    if any(x in model_name.lower() for x in ["vision", "llava", "bakllava"]):
                        capabilities.extend(["image-analysis", "multimodal"])
                    if any(x in model_name.lower() for x in ["instruct", "chat"]):
                        capabilities.append("conversation")
                    
                    # Generate performance metrics (mock data based on model characteristics)
                    performance = {
                        "speed": 4 if "llama" in model_name.lower() else 3,
                        "quality": 5 if any(x in model_name.lower() for x in ["llama", "mistral"]) else 4,
                        "memory": int(model_size / (1024**2)) if model_size else 1000  # MB
                    }
                    
                    # Determine description based on model name
                    description = None
                    if "llama" in model_name.lower():
                        description = "Meta's Llama model - excellent for code and reasoning"
                    elif "mistral" in model_name.lower():
                        description = "Mistral AI model - fast and efficient"
                    elif "qwen" in model_name.lower():
                        description = "Alibaba's Qwen model - strong multilingual capabilities"
                    elif "deepseek" in model_name.lower():
                        description = "DeepSeek model - specialized for coding tasks"
                    else:
                        description = f"AI model: {display_name}"
                    
                    model_info = ModelInfo(
                        name=model_name,
                        displayName=display_name,
                        status="available",
                        size=size_str,
                        description=description,
                        capabilities=capabilities,
                        performance=performance
                    )
                    models.append(model_info)
                
                logger.info(f"Retrieved {len(models)} models from Ollama")
                
            else:
                logger.warning(f"Ollama API returned status {response.status_code}")
                ollama_status = f"error_{response.status_code}"
                
        except requests.RequestException as e:
            logger.warning(f"Could not connect to Ollama: {e}")
            ollama_status = "connection_error"
        
        # If no models from Ollama, provide fallback models
        if not models:
            fallback_models = [
                ModelInfo(
                    name="mistral",
                    displayName="Mistral 7B",
                    status="offline" if ollama_status != "online" else "available",
                    description="Mistral AI 7B parameter model",
                    capabilities=["text-generation", "conversation", "code-generation"],
                    performance={"speed": 4, "quality": 4, "memory": 800}
                ),
                ModelInfo(
                    name="llama3.2",
                    displayName="Llama 3.2",
                    status="offline" if ollama_status != "online" else "available", 
                    description="Meta's Llama 3.2 model",
                    capabilities=["text-generation", "conversation", "code-generation", "reasoning"],
                    performance={"speed": 3, "quality": 5, "memory": 1200}
                ),
                ModelInfo(
                    name="qwen2.5-coder",
                    displayName="Qwen 2.5 Coder", 
                    status="offline" if ollama_status != "online" else "available",
                    description="Alibaba's Qwen 2.5 specialized for coding",
                    capabilities=["text-generation", "code-generation", "code-analysis"],
                    performance={"speed": 4, "quality": 5, "memory": 900}
                )
            ]
            models = fallback_models
            logger.info("Using fallback models list")
        
        return ModelsResponse(
            models=models,
            total=len(models),
            ollama_status=ollama_status
        )
        
    except Exception as e:
        logger.error(f"Error retrieving available models: {e}")
        
        # Return minimal fallback response
        fallback_models = [
            ModelInfo(
                name="offline-mode",
                displayName="Offline Mode",
                status="offline",
                description="Limited functionality when backend is unavailable",
                capabilities=["basic-editing"]
            )
        ]
        
        return ModelsResponse(
            models=fallback_models,
            total=1,
            ollama_status="error"
        )

@router.get("/status")
async def get_models_status(
    user: Dict = Depends(get_current_user)
):
    """Get the status of the model service (Ollama)"""
    try:
        ollama_url = os.getenv("OLLAMA_URL", "http://ollama:11434")
        
        try:
            api_key = os.getenv("OLLAMA_API_KEY", "key")
            headers = {"Authorization": f"Bearer {api_key}"} if api_key != "key" else {}
            response = requests.get(f"{ollama_url}/api/version", headers=headers, timeout=5)
            if response.status_code == 200:
                version_info = response.json()
                return {
                    "status": "online",
                    "service": "ollama",
                    "url": ollama_url,
                    "version": version_info.get("version", "unknown")
                }
            else:
                return {
                    "status": f"error_{response.status_code}",
                    "service": "ollama", 
                    "url": ollama_url,
                    "error": f"HTTP {response.status_code}"
                }
                
        except requests.RequestException as e:
            return {
                "status": "offline",
                "service": "ollama",
                "url": ollama_url, 
                "error": str(e)
            }
            
    except Exception as e:
        logger.error(f"Error checking model service status: {e}")
        return {
            "status": "error",
            "service": "unknown",
            "error": str(e)
        }

@router.post("/load/{model_name}")
async def load_model(
    model_name: str,
    user: Dict = Depends(get_current_user)
):
    """Load a specific model in Ollama"""
    try:
        ollama_url = os.getenv("OLLAMA_URL", "http://ollama:11434")
        
        # Send generate request with empty prompt to load model
        api_key = os.getenv("OLLAMA_API_KEY", "key")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key != "key" else {}
        response = requests.post(
            f"{ollama_url}/api/generate",
            json={
                "model": model_name,
                "prompt": "",
                "stream": False
            },
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            logger.info(f"Successfully loaded model {model_name}")
            return {"status": "success", "message": f"Model {model_name} loaded"}
        else:
            error_msg = f"Failed to load model {model_name}: HTTP {response.status_code}"
            logger.error(error_msg)
            raise HTTPException(status_code=400, detail=error_msg)
            
    except requests.RequestException as e:
        error_msg = f"Failed to connect to Ollama: {e}"
        logger.error(error_msg)
        raise HTTPException(status_code=503, detail=error_msg)
    except Exception as e:
        error_msg = f"Error loading model {model_name}: {e}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)