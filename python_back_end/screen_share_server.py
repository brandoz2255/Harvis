import socketio
from aiohttp import web
from screen_analyzer import analyze_image_base64
from vison_models.llm_connector import query_llm, unload_qwen_model, load_qwen_model, log_gpu_memory
import logging

logger = logging.getLogger(__name__)

# Create an SIO server instance
sio = socketio.AsyncServer(async_mode='aiohttp')
app = web.Application()
sio.attach(app)

# WebRTC peer connections tracking
connections = {}

@sio.event
async def connect(sid, environ):
    print(f"Client {sid} connected")
    connections[sid] = None

@sio.event
async def disconnect(sid):
    print(f"Client {sid} disconnected")
    if sid in connections:
        del connections[sid]

@sio.event
async def offer(sid, data):
    # Forward offer to all other clients (they will respond with an answer)
    for client_id, conn in connections.items():
        if client_id != sid and conn is not None:
            await sio.emit("offer", data, room=client_id)

@sio.event
async def answer(sid, data):
    # Forward answer to the client that sent the offer
    if sid in connections and connections[sid] is not None:
        await sio.emit("answer", data, room=connections[sid])

@sio.event
async def candidate(sid, data):
    # Forward ICE candidates to all clients
    for client_id in connections:
        if client_id != sid:
            await sio.emit("candidate", data, room=client_id)

@sio.event
async def screen_data(sid, data): # data is now an object { imageData, modelName }
    """
    Process screen data with intelligent model management.
    Automatically loads Qwen2VL when needed and manages memory efficiently.
    """
    try:
        # Process screen data
        image_data = data.get("imageData")
        model_name = data.get("modelName", "mistral") # Default to mistral if not provided
        
        logger.info(f"🖼️ Processing screen data for client {sid} with model {model_name}")
        
        # Log memory before processing
        log_gpu_memory("before screen processing")
        
        # Ensure Qwen2VL is loaded for screen analysis
        load_qwen_model()
        
        analysis_results = analyze_image_base64(image_data)
        if "error" in analysis_results:
            logger.error(f"Screen analysis error: {analysis_results['error']}")
            await sio.emit("error", {"message": analysis_results['error']}, room=sid)
            return

        caption = analysis_results.get("caption", "")
        ocr_text = analysis_results.get("ocr_text", "")

        # Unload Qwen2VL immediately after screen analysis
        logger.info("🔄 Unloading Qwen2VL after screen analysis")
        unload_qwen_model()
        
        # Generate LLM response
        llm_prompt = f"Analyze the following screen content. Caption: {caption}. OCR text: {ocr_text}. Provide a concise summary or relevant insights."
        llm_response = query_llm(llm_prompt, model_name=model_name)

        logger.info(f"✅ Screen analysis complete for client {sid}")
        await sio.emit("llm_response", {
            "caption": caption, 
            "llm_response": llm_response,
            "model_used": model_name,
            "processing_info": "Qwen2VL + " + model_name,
            "memory_management": "✅ Qwen2VL unloaded after use"
        }, room=sid)
        
    except Exception as e:
        logger.error(f"Screen data processing failed for client {sid}: {e}")
        await sio.emit("error", {"message": f"Processing failed: {str(e)}"}, room=sid)

@sio.event
async def stopShare(sid):
    """
    Handle screen share stopping and optionally unload models to free memory
    """
    logger.info(f"🛑 Client {sid} stopped screen sharing")
    if sid in connections and connections[sid] is not None:
        connections[sid] = None
    
    # Optional: Unload Qwen2VL if no active connections
    active_connections = sum(1 for conn in connections.values() if conn is not None)
    if active_connections == 0:
        logger.info("🗑️ No active screen shares, unloading Qwen2VL to free memory")
        unload_qwen_model()

# Start the server
if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=5001)
