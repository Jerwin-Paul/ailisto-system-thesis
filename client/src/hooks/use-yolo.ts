import { useRef, useCallback, useState, useEffect } from "react";
import { io, Socket } from "socket.io-client";

const YOLO_SERVER_URL = "http://4.216.188.104:5000";
const FRAME_INTERVAL_MS = 200; // 5 FPS

export interface Detection {
  box: [number, number, number, number]; // [x1, y1, x2, y2]
  conf: number;
  cls: number;
}

// COCO class names for YOLOv8n
const COCO_CLASSES: Record<number, string> = {
  0: "person",
  1: "bicycle",
  2: "car",
  3: "motorcycle",
  4: "airplane",
  5: "bus",
  6: "train",
  7: "truck",
  8: "boat",
  9: "traffic light",
  10: "fire hydrant",
  11: "stop sign",
  12: "parking meter",
  13: "bench",
  14: "bird",
  15: "cat",
  16: "dog",
  17: "elephant",
  24: "backpack",
  25: "umbrella",
  26: "handbag",
  27: "tie",
  28: "suitcase",
  39: "bottle",
  41: "cup",
  42: "fork",
  43: "knife",
  44: "spoon",
  45: "bowl",
  56: "chair",
  57: "couch",
  58: "potted plant",
  59: "bed",
  60: "dining table",
  62: "tv",
  63: "laptop",
  64: "mouse",
  65: "remote",
  66: "keyboard",
  67: "cell phone",
  72: "refrigerator",
  73: "book",
};

export function getClassName(cls: number): string {
  return COCO_CLASSES[cls] ?? `class_${cls}`;
}

export function useYolo() {
  const socketRef = useRef<Socket | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const captureCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const [detections, setDetections] = useState<Detection[]>([]);
  const [isConnected, setIsConnected] = useState(false);

  // Create a hidden canvas for capturing frames (won't interfere with the overlay canvas)
  useEffect(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 640;
    canvas.height = 480;
    captureCanvasRef.current = canvas;
    return () => {
      captureCanvasRef.current = null;
    };
  }, []);

  const connect = useCallback(() => {
    if (socketRef.current?.connected) return;

    const socket = io(YOLO_SERVER_URL, {
      transports: ["websocket", "polling"],
      reconnection: true,
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
    });

    socket.on("connect", () => {
      console.log("[YOLO] Connected to server:", socket.id);
      setIsConnected(true);
    });

    socket.on("disconnect", () => {
      console.log("[YOLO] Disconnected from server");
      setIsConnected(false);
    });

    socket.on("detections", (data: Detection[]) => {
      setDetections(data);
    });

    socket.on("connect_error", (err) => {
      console.error("[YOLO] Connection error:", err.message);
    });

    socketRef.current = socket;
  }, []);

  const disconnect = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (socketRef.current) {
      socketRef.current.disconnect();
      socketRef.current = null;
    }
    setDetections([]);
    setIsConnected(false);
  }, []);

  const startStreaming = useCallback((videoElement: HTMLVideoElement) => {
    if (!socketRef.current || intervalRef.current) return;

    intervalRef.current = setInterval(() => {
      if (!socketRef.current?.connected) return;
      if (!captureCanvasRef.current) return;
      if (videoElement.readyState < 2) return; // HAVE_CURRENT_DATA

      const canvas = captureCanvasRef.current;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      ctx.drawImage(videoElement, 0, 0, canvas.width, canvas.height);

      // Convert to JPEG base64 and strip the data URL prefix
      const dataUrl = canvas.toDataURL("image/jpeg", 0.7);
      const base64Data = dataUrl.split(",")[1];

      socketRef.current.emit("frame", base64Data);
    }, FRAME_INTERVAL_MS);
  }, []);

  const stopStreaming = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    setDetections([]);
  }, []);

  // Draw bounding boxes on a canvas overlay
  const drawDetections = useCallback(
    (
      canvas: HTMLCanvasElement,
      video: HTMLVideoElement,
      currentDetections: Detection[]
    ) => {
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      const displayWidth = canvas.width;
      const displayHeight = canvas.height;

      // Scale factors from the 640x480 capture resolution to the overlay canvas size
      const scaleX = displayWidth / 640;
      const scaleY = displayHeight / 480;

      ctx.clearRect(0, 0, displayWidth, displayHeight);

      for (const det of currentDetections) {
        const [x1, y1, x2, y2] = det.box;
        const sx1 = x1 * scaleX;
        const sy1 = y1 * scaleY;
        const sx2 = x2 * scaleX;
        const sy2 = y2 * scaleY;
        const w = sx2 - sx1;
        const h = sy2 - sy1;

        const label = `${getClassName(det.cls)} ${(det.conf * 100).toFixed(0)}%`;

        // Draw box
        ctx.strokeStyle = "#00ff00";
        ctx.lineWidth = 2;
        ctx.strokeRect(sx1, sy1, w, h);

        // Draw label background
        ctx.font = "bold 14px Arial";
        const textWidth = ctx.measureText(label).width;
        ctx.fillStyle = "rgba(0, 0, 0, 0.7)";
        ctx.fillRect(sx1, sy1 - 22, textWidth + 8, 22);

        // Draw label text
        ctx.fillStyle = "#00ff00";
        ctx.fillText(label, sx1 + 4, sy1 - 6);
      }
    },
    []
  );

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  return {
    detections,
    isConnected,
    connect,
    disconnect,
    startStreaming,
    stopStreaming,
    drawDetections,
  };
}
