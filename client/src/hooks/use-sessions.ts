import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type StartSessionRequest, buildUrl } from "@shared/routes";
import { useToast } from "@/hooks/use-toast";

export function useSessions() {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const sessionsQuery = useQuery({
    queryKey: [api.sessions.list.path],
    queryFn: async () => {
      const res = await fetch(api.sessions.list.path);
      if (!res.ok) throw new Error("Failed to fetch sessions");
      return api.sessions.list.responses[200].parse(await res.json());
    },
  });

  const startSessionMutation = useMutation({
    mutationFn: async (data: StartSessionRequest) => {
      const res = await fetch(api.sessions.start.path, {
        method: api.sessions.start.method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error("Failed to start session");
      return api.sessions.start.responses[201].parse(await res.json());
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [api.sessions.list.path] });
      toast({ title: "Session Started", description: "Monitoring is now active." });
    },
  });

  const endSessionMutation = useMutation({
    mutationFn: async ({ id, summaryStats }: { id: number; summaryStats: any }) => {
      const url = buildUrl(api.sessions.end.path, { id });
      const res = await fetch(url, {
        method: api.sessions.end.method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ summaryStats }),
      });
      if (!res.ok) throw new Error("Failed to end session");
      return api.sessions.end.responses[200].parse(await res.json());
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [api.sessions.list.path] });
      queryClient.invalidateQueries({ queryKey: [api.stats.dashboard.path] }); // Refresh dashboard stats too
      toast({ title: "Session Ended", description: "Summary report saved." });
    },
  });

  const dashboardStatsQuery = useQuery({
    queryKey: [api.stats.dashboard.path],
    queryFn: async () => {
      const res = await fetch(api.stats.dashboard.path);
      if (!res.ok) throw new Error("Failed to fetch stats");
      return api.stats.dashboard.responses[200].parse(await res.json());
    },
  });

  return {
    sessions: sessionsQuery.data,
    isLoadingSessions: sessionsQuery.isLoading,
    startSession: startSessionMutation.mutateAsync,
    isStarting: startSessionMutation.isPending,
    endSession: endSessionMutation.mutateAsync,
    isEnding: endSessionMutation.isPending,
    dashboardStats: dashboardStatsQuery.data,
    isLoadingStats: dashboardStatsQuery.isLoading,
  };
}
