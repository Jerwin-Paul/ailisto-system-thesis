import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type CreateSubjectRequest, buildUrl } from "@shared/routes";
import { useToast } from "@/hooks/use-toast";

export function useSubjects() {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const subjectsQuery = useQuery({
    queryKey: [api.subjects.list.path],
    queryFn: async () => {
      const res = await fetch(api.subjects.list.path);
      if (!res.ok) throw new Error("Failed to fetch subjects");
      return res.json();
    },
  });

  const createSubjectMutation = useMutation({
    mutationFn: async (data: CreateSubjectRequest) => {
      const validated = api.subjects.create.input.parse(data);
      const res = await fetch(api.subjects.create.path, {
        method: api.subjects.create.method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(validated),
      });
      if (!res.ok) throw new Error("Failed to create subject");
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [api.subjects.list.path] });
      toast({ title: "Success", description: "Subject created successfully" });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  const deleteSubjectMutation = useMutation({
    mutationFn: async (id: number) => {
      const url = buildUrl(api.subjects.delete.path, { id });
      const res = await fetch(url, { method: api.subjects.delete.method });
      if (!res.ok) throw new Error("Failed to delete subject");
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [api.subjects.list.path] });
      toast({ title: "Success", description: "Subject deleted" });
    },
  });

  const updateSchedulesMutation = useMutation({
    mutationFn: async ({ subjectId, schedules }: { subjectId: number; schedules: { day: string; startTime: string; endTime: string; room?: string }[] }) => {
      const res = await fetch(`/api/subjects/${subjectId}/schedules`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ schedules }),
      });
      if (!res.ok) throw new Error("Failed to update schedules");
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [api.subjects.list.path] });
      toast({ title: "Success", description: "Schedules updated" });
    },
    onError: (error: Error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  return {
    subjects: subjectsQuery.data,
    isLoading: subjectsQuery.isLoading,
    createSubject: createSubjectMutation.mutate,
    isCreating: createSubjectMutation.isPending,
    deleteSubject: deleteSubjectMutation.mutate,
    isDeleting: deleteSubjectMutation.isPending,
    updateSchedules: updateSchedulesMutation.mutate,
    isUpdatingSchedules: updateSchedulesMutation.isPending,
  };
}
