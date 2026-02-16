import { useState, useRef, useEffect } from "react";
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
import { Play, Pause, Square, Camera, AlertCircle } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { LineChart, Line, ResponsiveContainer, YAxis } from "recharts";

export default function LiveSession() {
  const { subjects } = useSubjects();
  const { startSession, endSession } = useSessions();
  const { toast } = useToast();
  
  const [selectedSubject, setSelectedSubject] = useState<string>("");
  const [isSessionActive, setIsSessionActive] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState<number | null>(null);
  const [cameraStream, setCameraStream] = useState<MediaStream | null>(null);
  
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  
  // Simulated real-time stats
  const [attentionScore, setAttentionScore] = useState(0);
  const [attentionHistory, setAttentionHistory] = useState<{time: number, value: number}[]>([]);

  // Start Camera
  const startCamera = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true });
      setCameraStream(stream);
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
      }
    } catch (err) {
      toast({
        title: "Camera Error",
        description: "Could not access camera. Please check permissions.",
        variant: "destructive",
      });
    }
  };

  const handleStartSession = async () => {
    if (!selectedSubject) {
      toast({ title: "Select a class", description: "Please select a subject to start.", variant: "destructive" });
      return;
    }
    
    if (!cameraStream) {
      await startCamera();
    }

    try {
      const session = await startSession({ subjectId: parseInt(selectedSubject) });
      setCurrentSessionId(session.id);
      setIsSessionActive(true);
      setAttentionHistory([]);
    } catch (error) {
      // Error handled in hook
    }
  };

  const handleEndSession = async () => {
    if (currentSessionId) {
      await endSession({ 
        id: currentSessionId, 
        summaryStats: { 
          avgAttention: Math.round(attentionHistory.reduce((a, b) => a + b.value, 0) / attentionHistory.length) || 0,
          duration: attentionHistory.length * 2 // approx seconds
        }
      });
    }
    setIsSessionActive(false);
    setCurrentSessionId(null);
    
    // Stop camera
    cameraStream?.getTracks().forEach(track => track.stop());
    setCameraStream(null);
  };

  // Simulation Loop
  useEffect(() => {
    let interval: NodeJS.Timeout;
    
    if (isSessionActive) {
      interval = setInterval(() => {
        // 1. Generate random attention score
        const newScore = Math.floor(Math.random() * (100 - 60) + 60); // 60-100 range
        setAttentionScore(newScore);
        
        setAttentionHistory(prev => {
          const newHistory = [...prev, { time: Date.now(), value: newScore }];
          return newHistory.slice(-20); // Keep last 20 points
        });

        // 2. Draw overlay on canvas
        if (canvasRef.current && videoRef.current) {
          const ctx = canvasRef.current.getContext('2d');
          const width = canvasRef.current.width;
          const height = canvasRef.current.height;
          
          if (ctx) {
            ctx.clearRect(0, 0, width, height);
            
            // Draw random bounding boxes
            const numBoxes = Math.floor(Math.random() * 3) + 2;
            ctx.strokeStyle = '#00ff00';
            ctx.lineWidth = 2;
            ctx.font = '14px Arial';
            ctx.fillStyle = '#00ff00';
            
            for (let i = 0; i < numBoxes; i++) {
              const x = Math.random() * (width - 100);
              const y = Math.random() * (height - 100);
              ctx.strokeRect(x, y, 100, 100);
              ctx.fillText(`Attentive: ${(Math.random() * 0.2 + 0.8).toFixed(2)}`, x, y - 5);
            }
          }
        }
      }, 2000); // Update every 2s
    }

    return () => clearInterval(interval);
  }, [isSessionActive]);

  return (
    <SidebarLayout>
      <div className="max-w-5xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold font-display text-slate-900">Live Session Monitoring</h1>
          <div className="flex items-center gap-3">
             <Select value={selectedSubject} onValueChange={setSelectedSubject} disabled={isSessionActive}>
              <SelectTrigger className="w-[250px] bg-white">
                <SelectValue placeholder="Select Class & Section" />
              </SelectTrigger>
              <SelectContent>
                {subjects?.map((s) => (
                  <SelectItem key={s.id} value={s.id.toString()}>
                    {s.name} ({s.section})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            
            {!isSessionActive ? (
              <Button 
                onClick={handleStartSession}
                className="bg-emerald-600 hover:bg-emerald-700 text-white gap-2 shadow-lg shadow-emerald-600/20"
              >
                <Play className="w-4 h-4" /> Start Session
              </Button>
            ) : (
              <Button 
                onClick={handleEndSession}
                variant="destructive"
                className="gap-2 shadow-lg shadow-red-600/20"
              >
                <Square className="w-4 h-4" /> End Session
              </Button>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Main Video Feed */}
          <div className="lg:col-span-2 space-y-4">
            <div className="relative aspect-video bg-black rounded-2xl overflow-hidden shadow-2xl border border-slate-800">
              {isSessionActive || cameraStream ? (
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
                  <div className="absolute top-4 left-4 bg-black/60 backdrop-blur-sm text-white px-3 py-1 rounded-full text-xs font-mono flex items-center gap-2">
                    <div className="w-2 h-2 bg-red-500 rounded-full animate-pulse"></div>
                    LIVE FEED
                  </div>
                </>
              ) : (
                <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-4">
                  <div className="w-16 h-16 rounded-full bg-slate-900 flex items-center justify-center">
                    <Camera className="w-8 h-8" />
                  </div>
                  <p>Start a session to enable camera feed</p>
                </div>
              )}
            </div>
          </div>

          {/* Real-time Stats Panel */}
          <div className="space-y-6">
             <Card className="border-none shadow-lg">
               <CardContent className="p-6 text-center space-y-2">
                 <p className="text-sm font-medium text-slate-500">Current Attention Score</p>
                 <div className={`text-5xl font-bold font-display transition-colors ${
                   attentionScore > 80 ? 'text-emerald-600' : attentionScore > 60 ? 'text-amber-500' : 'text-red-500'
                 }`}>
                   {isSessionActive ? attentionScore : '--'}%
                 </div>
                 <p className="text-xs text-slate-400">Updated in real-time</p>
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
                   {attentionScore > 80 
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
