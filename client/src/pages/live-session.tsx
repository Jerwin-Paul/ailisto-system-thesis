import { useState, useRef, useEffect, useCallback } from "react";
import { SidebarLayout } from "@/components/layout-sidebar";
import { useSubjects } from "@/hooks/use-subjects";
import { useSessions } from "@/hooks/use-sessions";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Play, Pause, Square, Camera, CameraOff, AlertCircle, Video } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { useYolo, getClassName } from "@/hooks/use-yolo";
import { LineChart, Line, ResponsiveContainer, YAxis } from "recharts";

interface CameraDevice {
  deviceId: string;
  label: string;
}

export default function LiveSession() {
  const { subjects } = useSubjects();
  const { startSession, endSession } = useSessions();
  const { toast } = useToast();
  const {
    detections,
    isConnected: isYoloConnected,
    connect: connectYolo,
    disconnect: disconnectYolo,
    startStreaming,
    stopStreaming,
    drawDetections,
  } = useYolo();

  const [selectedSubject, setSelectedSubject] = useState<string>("");
  const [isSessionActive, setIsSessionActive] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState<number | null>(null);
  const [cameraStream, setCameraStream] = useState<MediaStream | null>(null);

  // Camera selection
  const [cameras, setCameras] = useState<CameraDevice[]>([]);
  const [selectedCamera, setSelectedCamera] = useState<string>("");
  const [isCameraReady, setIsCameraReady] = useState(false);
  const [cameraToggle, setCameraToggle] = useState(() => localStorage.getItem('cameraToggle') === 'on');

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Simulated real-time stats
  const [attentionScore, setAttentionScore] = useState(0);
  const [attentionHistory, setAttentionHistory] = useState<{ time: number, value: number }[]>([]);

  // Enumerate cameras on mount
  useEffect(() => {
    async function loadCameras() {
      try {
        // Request permission first to get labeled devices
        const tempStream = await navigator.mediaDevices.getUserMedia({ video: true });
        tempStream.getTracks().forEach(t => t.stop());

        const devices = await navigator.mediaDevices.enumerateDevices();
        const videoDevices = devices
          .filter(d => d.kind === "videoinput")
          .map((d, i) => ({
            deviceId: d.deviceId,
            label: d.label || `Camera ${i + 1}`,
          }));
        setCameras(videoDevices);
        if (videoDevices.length > 0) {
          setSelectedCamera(videoDevices[0].deviceId);
        }
      } catch {
        toast({
          title: "Camera Access",
          description: "Please allow camera access to use this feature.",
          variant: "destructive",
        });
      }
    }
    loadCameras();
  }, []);

  // Auto-start camera when selectedCamera changes, but only if toggle is on
  useEffect(() => {
    if (selectedCamera && cameraToggle) {
      startCamera(selectedCamera);
    }
  }, [selectedCamera, cameraToggle]);

  // Keep video element in sync with stream
  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.srcObject = cameraStream;
      if (cameraStream) {
        videoRef.current.play().catch(() => { });
      }
    }
  }, [cameraStream]);

  // Cleanup stream on unmount
  useEffect(() => {
    return () => {
      setCameraStream(prev => {
        prev?.getTracks().forEach(t => t.stop());
        return null;
      });
    };
  }, []);

  // Start camera preview with selected device
  const startCamera = useCallback(async (deviceId: string) => {
    // Stop existing stream
    if (cameraStream) {
      cameraStream.getTracks().forEach(t => t.stop());
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { deviceId: { exact: deviceId } },
      });
      setCameraStream(stream);
      setIsCameraReady(true);
    } catch {
      toast({
        title: "Camera Error",
        description: "Could not access the selected camera.",
        variant: "destructive",
      });
      setIsCameraReady(false);
    }
  }, [cameraStream, toast]);

  // When camera selection changes
  const handleCameraChange = (deviceId: string) => {
    setSelectedCamera(deviceId);
  };

  // Toggle camera on/off (persists across navigation)
  const toggleCamera = () => {
    if (isCameraReady && cameraStream) {
      cameraStream.getTracks().forEach(t => t.stop());
      setCameraStream(null);
      setIsCameraReady(false);
      setCameraToggle(false);
      localStorage.setItem('cameraToggle', 'off');
      if (videoRef.current) {
        videoRef.current.srcObject = null;
      }
    } else if (selectedCamera) {
      setCameraToggle(true);
      localStorage.setItem('cameraToggle', 'on');
      startCamera(selectedCamera);
    }
  };

  // Start session
  const handleStartSession = async () => {
    if (!selectedSubject) {
      toast({ title: "Select a class", description: "Please select a subject first.", variant: "destructive" });
      return;
    }
    if (!isCameraReady) {
      toast({ title: "No camera", description: "Please select and preview a camera first.", variant: "destructive" });
      return;
    }

    try {
      const session = await startSession({ subjectId: parseInt(selectedSubject) });
      setCurrentSessionId(session.id);
      setIsSessionActive(true);
      setIsPaused(false);
      setAttentionHistory([]);

      // Connect to YOLO server and start streaming frames
      connectYolo();
      if (videoRef.current) {
        // Small delay to ensure socket connects before streaming
        setTimeout(() => {
          if (videoRef.current) {
            startStreaming(videoRef.current);
          }
        }, 500);
      }
    } catch {
      // Error handled in hook
    }
  };

  // Pause/Resume session
  const handlePauseResume = () => {
    setIsPaused(prev => !prev);
    toast({
      title: isPaused ? "Session Resumed" : "Session Paused",
      description: isPaused ? "Monitoring has resumed." : "Monitoring is paused. Camera is still active.",
    });
  };

  // End session
  const handleEndSession = async () => {
    // Stop YOLO streaming and disconnect
    stopStreaming();
    disconnectYolo();

    if (currentSessionId) {
      await endSession({
        id: currentSessionId,
        summaryStats: {
          avgAttention: Math.round(attentionHistory.reduce((a, b) => a + b.value, 0) / attentionHistory.length) || 0,
          duration: attentionHistory.length * 2,
        },
      });
    }
    setIsSessionActive(false);
    setIsPaused(false);
    setCurrentSessionId(null);

    // Clear canvas
    if (canvasRef.current) {
      const ctx = canvasRef.current.getContext("2d");
      if (ctx) ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
    }

    // Stop camera
    cameraStream?.getTracks().forEach(track => track.stop());
    setCameraStream(null);
    setIsCameraReady(false);
  };

  // Draw YOLO detections on the canvas whenever they update
  useEffect(() => {
    if (isSessionActive && !isPaused && canvasRef.current && videoRef.current) {
      drawDetections(canvasRef.current, videoRef.current, detections);

      // Update attention score based on number of person detections
      const personCount = detections.filter(d => d.cls === 0).length;
      if (detections.length > 0) {
        // Simple heuristic: attention based on person detection confidence
        const personDetections = detections.filter(d => d.cls === 0);
        const avgConf = personDetections.length > 0
          ? personDetections.reduce((sum, d) => sum + d.conf, 0) / personDetections.length
          : 0;
        const newScore = Math.round(avgConf * 100);
        setAttentionScore(newScore);

        setAttentionHistory(prev => {
          const newHistory = [...prev, { time: Date.now(), value: newScore }];
          return newHistory.slice(-20);
        });
      }
    }
  }, [detections, isSessionActive, isPaused, drawDetections]);

  // Pause/resume YOLO streaming
  useEffect(() => {
    if (isSessionActive && videoRef.current) {
      if (isPaused) {
        stopStreaming();
      } else {
        startStreaming(videoRef.current);
      }
    }
  }, [isPaused, isSessionActive, startStreaming, stopStreaming]);

  // Clear canvas when paused
  useEffect(() => {
    if (isPaused && canvasRef.current) {
      const ctx = canvasRef.current.getContext("2d");
      if (ctx) {
        ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
      }
    }
  }, [isPaused]);

  return (
    <SidebarLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="mb-2">
          <h1 className="text-2xl font-bold font-display text-slate-900">Live Session Monitoring</h1>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Main Video Feed + Controls */}
          <div className="lg:col-span-2 space-y-4">
            {/* Camera & Class Selector Row */}
            <div className="flex items-center gap-3">
              {/* Camera toggle button */}
              <Button
                variant={isCameraReady ? "default" : "outline"}
                size="icon"
                className={`shrink-0 rounded-xl h-10 w-10 transition-all ${isCameraReady
                  ? "bg-primary text-white shadow-lg shadow-primary/25"
                  : "text-slate-500 hover:text-slate-700"
                  }`}
                onClick={toggleCamera}
                disabled={!selectedCamera || isSessionActive}
                title={isCameraReady ? "Turn off camera" : "Turn on camera"}
              >
                {isCameraReady ? <Camera className="w-4 h-4" /> : <CameraOff className="w-4 h-4" />}
              </Button>

              {/* Camera dropdown */}
              <Select
                value={selectedCamera}
                onValueChange={handleCameraChange}
                disabled={isSessionActive}
              >
                <SelectTrigger className="flex-1 bg-white rounded-xl">
                  <SelectValue placeholder="Choose a camera..." />
                </SelectTrigger>
                <SelectContent>
                  {cameras.map((cam) => (
                    <SelectItem key={cam.deviceId} value={cam.deviceId}>
                      {cam.label}
                    </SelectItem>
                  ))}
                  {cameras.length === 0 && (
                    <div className="px-3 py-2 text-sm text-slate-400">No cameras found</div>
                  )}
                </SelectContent>
              </Select>

              {/* Class & Section dropdown */}
              <Select value={selectedSubject} onValueChange={setSelectedSubject} disabled={isSessionActive}>
                <SelectTrigger className="w-[220px] bg-white rounded-xl shrink-0">
                  <SelectValue placeholder="Select Class" />
                </SelectTrigger>
                <SelectContent>
                  {subjects?.map((s) => (
                    <SelectItem key={s.id} value={s.id.toString()}>
                      {s.name} ({s.section})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Video Area */}
            <div className="relative aspect-video bg-black rounded-2xl overflow-hidden shadow-2xl border border-slate-800">
              {isCameraReady ? (
                <>
                  <video
                    ref={videoRef}
                    autoPlay
                    muted
                    playsInline
                    className="w-full h-full object-cover"
                  />
                  <canvas
                    ref={canvasRef}
                    className="absolute inset-0 w-full h-full pointer-events-none"
                    width={800}
                    height={450}
                  />
                  {isSessionActive && (
                    <div className="absolute top-4 left-4 flex flex-col gap-2">
                      <div className="bg-black/60 backdrop-blur-sm text-white px-3 py-1.5 rounded-full text-xs font-mono flex items-center gap-2">
                        <div className={`w-2 h-2 rounded-full ${isPaused ? "bg-amber-400" : "bg-red-500 animate-pulse"}`} />
                        {isPaused ? "PAUSED" : "LIVE FEED"}
                      </div>
                      <div className="bg-black/60 backdrop-blur-sm text-white px-3 py-1.5 rounded-full text-xs font-mono flex items-center gap-2">
                        <div className={`w-2 h-2 rounded-full ${isYoloConnected ? "bg-emerald-400" : "bg-red-400"}`} />
                        {isYoloConnected ? `YOLO · ${detections.length} detected` : "YOLO connecting..."}
                      </div>
                    </div>
                  )}
                  {!isSessionActive && (
                    <div className="absolute top-4 left-4 bg-black/60 backdrop-blur-sm text-white px-3 py-1.5 rounded-full text-xs font-mono flex items-center gap-2">
                      <div className="w-2 h-2 bg-emerald-400 rounded-full" />
                      CAMERA PREVIEW
                    </div>
                  )}
                </>
              ) : (
                <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-4">
                  <div className="w-16 h-16 rounded-full bg-slate-900 flex items-center justify-center">
                    <Camera className="w-8 h-8" />
                  </div>
                  <p className="text-sm">Select a camera to start preview</p>
                </div>
              )}
            </div>

            {/* Session Control Buttons */}
            <div className="flex items-center justify-center gap-3 py-2">
              {!isSessionActive ? (
                <Button
                  size="lg"
                  onClick={handleStartSession}
                  disabled={!isCameraReady || !selectedSubject}
                  className="bg-emerald-600 hover:bg-emerald-700 text-white gap-2 rounded-xl px-8 shadow-lg shadow-emerald-600/20 transition-all"
                >
                  <Play className="w-5 h-5" />
                  Start Session
                </Button>
              ) : (
                <>
                  <Button
                    size="lg"
                    variant="outline"
                    onClick={handlePauseResume}
                    className={`gap-2 rounded-xl px-6 transition-all ${isPaused
                      ? "border-emerald-300 text-emerald-700 hover:bg-emerald-50"
                      : "border-amber-300 text-amber-700 hover:bg-amber-50"
                      }`}
                  >
                    {isPaused ? (
                      <><Play className="w-5 h-5" /> Resume</>
                    ) : (
                      <><Pause className="w-5 h-5" /> Pause</>
                    )}
                  </Button>
                  <Button
                    size="lg"
                    variant="destructive"
                    onClick={handleEndSession}
                    className="gap-2 rounded-xl px-6 shadow-lg shadow-red-600/20 transition-all"
                  >
                    <Square className="w-5 h-5" />
                    End Session
                  </Button>
                </>
              )}
            </div>
          </div>

          {/* Real-time Stats Panel */}
          <div className="space-y-6">
            <Card className="border-none shadow-lg">
              <CardContent className="p-6 text-center space-y-2">
                <p className="text-sm font-medium text-slate-500">Current Attention Score</p>
                <div className={`text-5xl font-bold font-display transition-colors ${attentionScore > 80 ? "text-emerald-600" : attentionScore > 60 ? "text-amber-500" : "text-red-500"
                  }`}>
                  {isSessionActive && !isPaused ? attentionScore : "--"}%
                </div>
                <p className="text-xs text-slate-400">
                  {isPaused ? "Monitoring paused" : "Updated in real-time"}
                </p>
              </CardContent>
            </Card>

            <Card className="border-none shadow-lg h-64">
              <CardContent className="p-4 h-full">
                <p className="text-sm font-medium text-slate-500 mb-4">Attention Trend (Last 1m)</p>
                <div className="h-40 w-full">
                  {isSessionActive && attentionHistory.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={attentionHistory}>
                        <YAxis domain={[0, 100]} hide />
                        <Line
                          type="monotone"
                          dataKey="value"
                          stroke="#2563eb"
                          strokeWidth={3}
                          dot={false}
                          isAnimationActive={false}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="h-full flex items-center justify-center text-slate-300 text-xs italic">
                      Waiting for data...
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>

            <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 flex gap-3">
              <AlertCircle className="w-5 h-5 text-blue-600 shrink-0" />
              <div>
                <h4 className="text-sm font-semibold text-blue-900">AI Insight</h4>
                <p className="text-xs text-blue-700 mt-1">
                  {!isSessionActive
                    ? "Start a session to receive AI-powered insights."
                    : isPaused
                      ? "Session is paused. Resume to continue monitoring."
                      : attentionScore > 80
                        ? "Great engagement! The class seems focused."
                        : attentionScore > 60
                          ? "Attention is fluctuating. Try asking a question to re-engage."
                          : "Low attention detected. Consider a short break or activity change."}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </SidebarLayout>
  );
}
