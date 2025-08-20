"""Configuration and utility functions for VibeCoading containers."""

import os
import logging
import docker
from typing import Optional

logger = logging.getLogger(__name__)

# Container image configuration
VIBECODING_IMAGE = os.getenv("VIBECODING_IMAGE", "vibecoding-optimized:latest")

def ensure_image(client: docker.DockerClient, image_name: Optional[str] = None) -> str:
    """
    Ensure the VibeCoading image is available, pulling if necessary.
    
    Args:
        client: Docker client instance
        image_name: Optional image name override, defaults to VIBECODING_IMAGE
    
    Returns:
        str: The verified image name
        
    Raises:
        docker.errors.ImageNotFound: If image doesn't exist and can't be pulled
        docker.errors.APIError: If pull fails due to network/auth issues
    """
    if image_name is None:
        image_name = VIBECODING_IMAGE
    
    try:
        # Try to get the image locally first
        image = client.images.get(image_name)
        logger.info(f"✅ Image {image_name} found locally")
        return image_name
    except docker.errors.ImageNotFound:
        # Image not found locally, try to pull it
        logger.info(f"📥 Image {image_name} not found locally, attempting to pull...")
        
        try:
            # Attempt to pull the image
            image = client.images.pull(image_name)
            logger.info(f"✅ Successfully pulled image {image_name}")
            return image_name
        except docker.errors.NotFound:
            # Repository doesn't exist
            error_msg = f"Image repository '{image_name}' does not exist or access is denied. Please check the image name and registry access."
            logger.error(f"❌ {error_msg}")
            raise docker.errors.ImageNotFound(error_msg)
        except docker.errors.APIError as e:
            # Network or authentication error
            error_msg = f"Failed to pull image '{image_name}': {str(e)}"
            logger.error(f"❌ {error_msg}")
            raise docker.errors.APIError(error_msg)
        except Exception as e:
            # Unexpected error
            error_msg = f"Unexpected error while pulling image '{image_name}': {str(e)}"
            logger.error(f"❌ {error_msg}")
            raise docker.errors.APIError(error_msg)