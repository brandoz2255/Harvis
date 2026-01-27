"use client"

import { useState, useRef, useEffect, useCallback } from "react";
import io from "socket.io-client";
import { motion } from "framer-motion";
import { Monitor, MonitorOff, Eye, EyeOff, MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useChatStore } from "@/stores/chatStore";

const SOCKET_SERVER_URL = process.env.NEXT_PUBLIC_SOCKET_SERVER_URL || "http://backend:5000";
const socket = io(SOCKET_SERVER_URL);

// WebRTC configuration
const RTC_CONFIGURATION = {
  iceServers: [
    { urls: "stun:stun.l.google.com:19302" }
  ]
};

export default function ScreenShare() {
  const [isSharing, setIsSharing] = useState<boolean>(false);
  const [commentaryEnabled, setCommentaryEnabled] = useState<boolean>(false);
  const [commentary, setCommentary] = useState<string>("");
  const [llmResponse, setLlmResponse] = useState<string>("");
  const [isAnalyzing, setIsAnalyzing] = useState<boolean>(false);
  const [selectedModel, setSelectedModel] = useState<string>("mistral");
  const [availableModels, setAvailableModels] = useState<string[]>(["mistral", "llama2", "gemini-pro"]);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const commentaryTimerRef = useRef<NodeJS.Timeout | null>(null);
  const peerConnectionRef = useRef<RTCPeerConnection | null>(null);

  const addMessage = useChatStore((state: any) => state.addMessage);

  // Handle signaling
  useEffect(() => {
    socket.on("offer", async (offer: RTCSessionDescriptionInit) => {
      if (!peerConnectionRef.current) return;

      await peerConnectionRef.current.setRemoteDescription(new RTCSessionDescription(offer));
      const answer = await peerConnectionRef.current.createAnswer();
      await peerConnectionRef.current.setLocalDescription(answer);
      socket.emit("answer", answer);
    });

    socket.on("answer", async (answer: RTCSessionDescriptionInit) => {
      if (!peerConnectionRef.current) return;
      await peerConnectionRef.current.setRemoteDescription(new RTCSessionDescription(answer));
    });

    socket.on("candidate", async (candidate: RTCIceCandidateInit) => {
      if (!peerConnectionRef.current) return;
      await peerConnectionRef.current.addIceCandidate(new RTCIceCandidate(candidate));
    });

    socket.on("llm_response", (data: { blip_description: string; llm_response: string }) => {
      if (data.blip_description) {
        setCommentary(data.blip_description);
      }
      if (data.llm_response) {
        console.log("LLM Response:", data.llm_response);
        setLlmResponse(data.llm_response);
        addMessage({
          role: "assistant",
          content: data.llm_response,
        });
      }
      setIsAnalyzing(false);
    });

    // Fetch available models from the backend
    const fetchModels = async () => {
      try {
        const response = await fetch("/api/ollama-models");
        if (response.ok) {
          const models = await response.json();
          setAvailableModels(models);
          if (models.length > 0 && !models.includes(selectedModel)) {
            setSelectedModel(models[0]); // Set default to first available if current is not in list
          }
        }
      } catch (error) {
        console.error("Error fetching models:", error);
      }
    };

    fetchModels();

  }, [addMessage, selectedModel]);

  const startScreenShare = async () => {
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        audio: false,
      });

      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        streamRef.current = stream;
        setIsSharing(true);

        // Set up WebRTC peer connection
        const peerConnection = new RTCPeerConnection(RTC_CONFIGURATION);
        stream.getTracks().forEach(track => peerConnection.addTrack(track, stream));

        peerConnection.onicecandidate = (event) => {
          if (event.candidate) {
            socket.emit("candidate", event.candidate);
          }
        };

        peerConnection.ontrack = (event) => {
          if (videoRef.current) {
            videoRef.current.srcObject = event.streams[0];
          }
        };

        // Create offer and send to server
        const offer = await peerConnection.createOffer();
        await peerConnection.setLocalDescription(offer);
        socket.emit("offer", offer);

        peerConnectionRef.current = peerConnection;

        stream.getVideoTracks()[0].addEventListener("ended", stopScreenShare);
      }
    } catch (error) {
      console.error("Error starting screen share:", error);
      alert("Failed to start screen sharing. Please check permissions.");
    }
  };

  const stopScreenShare = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }

    if (peerConnectionRef.current) {
      peerConnectionRef.current.close();
      peerConnectionRef.current = null;

      // Send signal to server to stop sharing
      socket.emit("stopShare");
    }

    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }

    setIsSharing(false);
    setCommentaryEnabled(false);
    setCommentary("");
    setLlmResponse("");

    if (commentaryTimerRef.current) {
      clearInterval(commentaryTimerRef.current);
      commentaryTimerRef.current = null;
    }
  };

  const analyzeScreen = useCallback(async () => {
    if (!videoRef.current || !streamRef.current || isAnalyzing) return

    setIsAnalyzing(true)

    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const canvas = document.createElement("canvas")
        canvas.width = videoRef.current.videoWidth
        canvas.height = videoRef.current.videoHeight

        const ctx = canvas.getContext("2d")
        if (ctx) {
          ctx.drawImage(videoRef.current, 0, 0)
          const imageData = canvas.toDataURL("image/jpeg", 0.8)

          socket.emit("screen_data", { imageData, modelName: selectedModel })

          

          setIsAnalyzing(false)
          return
        }
      } catch (error) {
        console.error(`Analyze attempt ${attempt + 1} failed:`, error)
        if (attempt === 2) {
          setCommentary("Sorry, can't analyze the screen.")
        }
        await new Promise((resolve) => setTimeout(resolve, 1000 * (attempt + 1)))
      }
    }
    setIsAnalyzing(false)
  }, [isAnalyzing, selectedModel])

  const toggleCommentary = () => {
    const newState = !commentaryEnabled
    setCommentaryEnabled(newState)

    if (newState && isSharing) {
      analyzeScreen()
      commentaryTimerRef.current = setInterval(analyzeScreen, 30000)
    } else {
      if (commentaryTimerRef.current) {
        clearInterval(commentaryTimerRef.current)
        commentaryTimerRef.current = null
      }
      setCommentary("")
      setLlmResponse("")
    }
  }

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "c" && isSharing) {
        e.preventDefault()
        analyzeScreen()
      }
    }

    document.addEventListener("keydown", handleKeyDown)
    return () => document.removeEventListener("keydown", handleKeyDown)
  }, [isSharing, analyzeScreen])

  useEffect(() => {
    return () => {
      if (commentaryTimerRef.current) {
        clearInterval(commentaryTimerRef.current)
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop())
      }
    }
  }, [])

  return (
    <Card className="bg-gray-900/50 backdrop-blur-sm border-blue-500/30 h-[600px] flex flex-col">
      <div className="p-4 border-b border-blue-500/30">
        <h2 className="text-xl font-semibold text-blue-300">Screen Share</h2>
      </div>

      <div className="p-4 space-y-4">
        <div className="flex space-x-2">
          <Button
            onClick={isSharing ? stopScreenShare : startScreenShare}
            className={`${isSharing ? "bg-red-600 hover:bg-red-700" : "bg-blue-600 hover:bg-blue-700"} text-white`}
          >
            {isSharing ? (
              <>
                <MonitorOff className="w-4 h-4 mr-2" />
                Stop Sharing
              </>
            ) : (
              <>
                <Monitor className="w-4 h-4 mr-2" />
                Start Sharing
              </>
            )}
          </Button>

          <Button
            onClick={toggleCommentary}
            disabled={!isSharing}
            variant="outline"
            className={`${
              commentaryEnabled
                ? "bg-green-600 hover:bg-green-700 text-white border-green-600"
                : "bg-gray-800 border-gray-600 text-gray-300 hover:bg-gray-700"
            }`}
          >
            {commentaryEnabled ? (
              <>
                <Eye className="w-4 h-4 mr-2" />
                Disable Commentary
              </>
            ) : (
              <>
                <EyeOff className="w-4 h-4 mr-2" />
                Enable Commentary
              </>
            )}
          </Button>
          <select
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
            className="p-2 rounded-md bg-gray-800 text-white border border-gray-600"
          >
            {availableModels.map((model) => (
              <option key={model} value={model}>
                {model}
              </option>
            ))}
          </select>
        </div>

        <div className="relative">
          <video
            ref={videoRef}
            autoPlay
            muted
            className={`w-full rounded-lg border border-gray-600 ${isSharing ? "block" : "hidden"}`}
            style={{ maxHeight: "300px" }}
          />

          {!isSharing && (
            <div className="w-full h-64 bg-gray-800 rounded-lg border border-gray-600 flex items-center justify-center">
              <div className="text-center text-gray-400">
                <Monitor className="w-12 h-12 mx-auto mb-2 opacity-50" />
                <p>Click &quot;Start Sharing&quot; to begin screen capture</p>
              </div>
            </div>
          )}
        </div>

        {(commentary || llmResponse) && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-blue-900/30 border border-blue-500/50 rounded-lg p-3 space-y-2"
          >
            {commentary && (
              <div className="flex items-start space-x-2">
                <Eye className="w-4 h-4 text-blue-400 mt-0.5 flex-shrink-0" />
                <div>
                  <p className="text-sm text-blue-300 font-medium">Screen Analysis</p>
                  <p className="text-sm text-gray-300 mt-1">{commentary}</p>
                </div>
              </div>
            )}

            {llmResponse && (
              <div className="flex items-start space-x-2">
                <MessageSquare className="w-4 h-4 text-green-400 mt-0.5 flex-shrink-0" />
                <div>
                  <p className="text-sm text-green-300 font-medium">AI Response</p>
                  <p className="text-sm text-gray-300 mt-1">{llmResponse}</p>
                </div>
              </div>
            )}

            {isAnalyzing && (
              <div className="flex items-center space-x-2 mt-2">
                <div className="w-2 h-2 bg-blue-400 rounded-full animate-pulse"></div>
                <span className="text-xs text-blue-400">Analyzing...</span>
              </div>
            )}
          </motion.div>
        )}
      </div>
    </Card>
  )
}
