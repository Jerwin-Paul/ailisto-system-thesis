import { useState } from "react";
import { SidebarLayout } from "@/components/layout-sidebar";
import { useSubjects } from "@/hooks/use-subjects";
import { useAuth } from "@/hooks/use-auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Plus, BookOpen, Trash2, Loader2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

const subjectSchema = z.object({
  name: z.string().min(1, "Subject name is required"),
  courseCode: z.string().min(1, "Course code is required"),
  section: z.string().min(1, "Section is required"),
  schedule: z.string().optional(),
});

export default function ClassesPage() {
  const { subjects, isLoading, createSubject, isCreating, deleteSubject, isDeleting } = useSubjects();
  const [isOpen, setIsOpen] = useState(false);

  const form = useForm<z.infer<typeof subjectSchema>>({
    resolver: zodResolver(subjectSchema),
    defaultValues: { name: "", courseCode: "", section: "", schedule: "" },
  });

  function onSubmit(values: z.infer<typeof subjectSchema>) {
    createSubject(values, {
      onSuccess: () => {
        setIsOpen(false);
        form.reset();
      },
    });
  }

  return (
    <SidebarLayout>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold font-display text-slate-900">Class Management</h1>
            <p className="text-slate-500">Manage your subjects and sections.</p>
          </div>
          <Dialog open={isOpen} onOpenChange={setIsOpen}>
            <DialogTrigger asChild>
              <Button className="rounded-xl shadow-lg shadow-primary/20 gap-2">
                <Plus className="w-4 h-4" /> Add Class
              </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-[425px]">
              <DialogHeader>
                <DialogTitle>Add New Class</DialogTitle>
              </DialogHeader>
              <Form {...form}>
                <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
                  <FormField
                    control={form.control}
                    name="name"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Subject Name</FormLabel>
                        <FormControl><Input placeholder="Mathematics" {...field} /></FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <div className="grid grid-cols-2 gap-4">
                    <FormField
                      control={form.control}
                      name="courseCode"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Code</FormLabel>
                          <FormControl><Input placeholder="MATH101" {...field} /></FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name="section"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Section</FormLabel>
                          <FormControl><Input placeholder="Section A" {...field} /></FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>
                  <FormField
                    control={form.control}
                    name="schedule"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Schedule (Optional)</FormLabel>
                        <FormControl><Input placeholder="Mon/Wed 10:00 AM" {...field} /></FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <Button type="submit" className="w-full" disabled={isCreating}>
                    {isCreating ? <Loader2 className="animate-spin w-4 h-4 mr-2" /> : null}
                    Create Class
                  </Button>
                </form>
              </Form>
            </DialogContent>
          </Dialog>
        </div>

        {isLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[1,2,3].map(i => <div key={i} className="h-40 bg-slate-100 rounded-2xl animate-pulse"></div>)}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {subjects?.map((subject) => (
              <Card key={subject.id} className="group hover:shadow-lg transition-all duration-300 border-slate-200">
                <CardContent className="p-6">
                  <div className="flex justify-between items-start mb-4">
                    <div className="w-12 h-12 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center group-hover:bg-blue-600 group-hover:text-white transition-colors">
                      <BookOpen className="w-6 h-6" />
                    </div>
                    <Button 
                      variant="ghost" 
                      size="icon" 
                      className="text-slate-400 hover:text-destructive hover:bg-destructive/10"
                      onClick={() => {
                        if (confirm("Are you sure you want to delete this class?")) {
                          deleteSubject(subject.id);
                        }
                      }}
                      disabled={isDeleting}
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>
                  <h3 className="font-bold font-display text-lg text-slate-900">{subject.name}</h3>
                  <div className="flex gap-2 text-sm text-slate-500 mt-1">
                    <span className="font-mono bg-slate-100 px-2 py-0.5 rounded text-xs">{subject.courseCode}</span>
                    <span>•</span>
                    <span>{subject.section}</span>
                  </div>
                  {subject.schedule && (
                    <p className="text-xs text-slate-400 mt-4 pt-4 border-t border-slate-100">
                      {subject.schedule}
                    </p>
                  )}
                </CardContent>
              </Card>
            ))}
            
            {subjects?.length === 0 && (
              <div className="col-span-full flex flex-col items-center justify-center py-12 text-slate-400 border-2 border-dashed border-slate-200 rounded-2xl">
                <BookOpen className="w-12 h-12 mb-4 opacity-50" />
                <p>No classes found. Add your first class to get started.</p>
              </div>
            )}
          </div>
        )}
      </div>
    </SidebarLayout>
  );
}
