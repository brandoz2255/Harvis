async def stream_ollama_chunks(endpoint, payload, timeout=3600):
    """
    Stream chunks from Ollama in a background thread to avoid blocking the asyncio loop.
    Yields raw line bytes from response.iter_lines().
    """
    import queue
    import threading
    
    # Queue for passing data from thread to async loop
    q = queue.Queue()
    
    def producer():
        try:
            # This is blocking, so we run it in a thread
            response = make_ollama_request(endpoint, payload, timeout=timeout, stream=True)
            
            if response.status_code != 200:
                q.put(Exception(f"Ollama error: {response.status_code} {response.text}"))
                return
                
            for line in response.iter_lines():
                if line:
                    q.put(line)
            q.put(None) # Sentinel for completion
        except Exception as e:
            q.put(e)
            
    # Start the producer thread
    t = threading.Thread(target=producer, daemon=True)
    t.start()
    
    # Consume the queue asynchronously
    loop = asyncio.get_running_loop()
    
    while True:
        # Use simple polling or run_in_executor to wait for queue items
        # asyncio.to_thread is ideal but requires Python 3.9+ (we have 3.11)
        try:
            item = await asyncio.to_thread(q.get)
            
            if item is None:
                break
                
            if isinstance(item, Exception):
                logger.error(f"Error in streaming thread: {item}")
                raise item
                
            yield item
            
        except Exception as e:
            # If explicit exception from producer, re-raise it
            raise e
