import socketio
from aiohttp import web
from screen_analyzer import analyze_image_base64
from llm_connector import query_llm

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
    # Process screen data
    image_data = data.get("imageData")
    model_name = data.get("modelName", "mistral") # Default to mistral if not provided

    analysis_results = analyze_image_base64(image_data)
    if "error" in analysis_results:
        print(f"Screen analysis error: {analysis_results['error']}")
        return

    caption = analysis_results.get("caption", "")
    ocr_text = analysis_results.get("ocr_text", "")

    llm_prompt = f"Analyze the following screen content. Caption: {caption}. OCR text: {ocr_text}. Provide a concise summary or relevant insights."
    llm_response = query_llm(llm_prompt, model_name=model_name)

    await sio.emit("llm_response", {"caption": caption, "llm_response": llm_response}, room=sid)

@sio.event
async def stopShare(sid):
    # Handle screen share stopping
    if sid in connections and connections[sid] is not None:
        connections[sid] = None

# Start the server
if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=5001)
