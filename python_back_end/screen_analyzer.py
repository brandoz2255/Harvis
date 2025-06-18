import base64
import io
from PIL import Image
import torch
from transformers.pipelines import pipeline
import logging
import json
from fastapi import FastAPI, HTTPException
import uvicorn

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Initialize the image analysis model
try:
    image_to_text = pipeline("image-to-text", model="Salesforce/blip-image-captioning-base")
    logger.info("Image analysis model loaded successfully")
except Exception as e:
    logger.error(f"Error loading image analysis model: {e}")
    image_to_text = None

def analyze_image(image_data: str) -> str:
    """Analyze the image and return a commentary."""
    try:
        # Remove the data URL prefix if present
        if ',' in image_data:
            image_data = image_data.split(',')[1]
        
        # Decode base64 image
        image_bytes = base64.b64decode(image_data)
        image = Image.open(io.BytesIO(image_bytes))
        
        # Generate caption
        if image_to_text:
            result = image_to_text(image)
            if isinstance(result, list) and len(result) > 0 and isinstance(result[0], dict):
                caption = result[0].get('generated_text', '')
                if caption:
                    # Add some context to make it more conversational
                    commentary = f"I see {caption.lower()}"
                    
                    # Add some variety to the commentary
                    prefixes = [
                        "Looking at your screen, ",
                        "I notice that ",
                        "On your screen, ",
                        "I can see that ",
                        "Currently, "
                    ]
                    
                    import random
                    commentary = random.choice(prefixes) + commentary
                    return commentary
            
            return "I'm having trouble analyzing the screen content right now."
        else:
            return "I'm having trouble analyzing the screen content right now."
            
    except Exception as e:
        logger.error(f"Error analyzing image: {e}")
        return "I'm having trouble analyzing the screen content right now."

@app.post("/analyze-screen")
async def analyze_screen(request: dict):
    """Endpoint to analyze screen content."""
    try:
        image_data = request.get('image')
        if not image_data:
            raise HTTPException(status_code=400, detail="No image data provided")
        
        commentary = analyze_image(image_data)
        return {"commentary": commentary}
        
    except Exception as e:
        logger.error(f"Error in analyze-screen endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001) 