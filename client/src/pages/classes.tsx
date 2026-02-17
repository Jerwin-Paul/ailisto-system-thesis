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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Plus, BookOpen, Trash2, Loader2, Calendar, Clock, MapPin, MoreVertical, Pencil, CalendarCheck, CalendarDays } from "lucide-react";
import { useForm, useFieldArray } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

const DAYS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];

const HOURS = Array.from({ length: 12 }, (_, i) => String(i + 1).padStart(2, "0"));
const MINUTES = Array.from({ length: 12 }, (_, i) => String(i * 5).padStart(2, "0"));

function parseTimeValue(value: string): { hour: string; minute: string; period: string } {
  if (!value) return { hour: "", minute: "", period: "AM" };
  // Expected format: "09:30 AM"
  const match = value.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i);
  if (match) return { hour: match[1].padStart(2, "0"), minute: match[2], period: match[3].toUpperCase() };
  return { hour: "", minute: "", period: "AM" };
}

const scheduleEntrySchema = z.object({
  day: z.string().min(1, "Day is required"),
  startTime: z.string().min(1, "Start time is required"),
  endTime: z.string().min(1, "End time is required"),
  room: z.string().optional().default(""),
});

const subjectSchema = z.object({
  name: z.string().min(1, "Subject name is required"),
  courseCode: z.string().min(1, "Course code is required"),
  section: z.string().min(1, "Section is required"),
  schedule: z.array(scheduleEntrySchema).optional().default([]),
});

const editScheduleSchema = z.object({
  schedules: z.array(scheduleEntrySchema),
});

type SubjectFormValues = z.infer<typeof subjectSchema>;
type EditScheduleFormValues = z.infer<typeof editScheduleSchema>;

// ── Schedule entry form rows (shared between Add Class and Edit Schedule) ──

function ScheduleEntryRow({
  index,
  control,
  namePrefix,
  onRemove,
}: {
  index: number;
  control: any;
  namePrefix: string;
  onRemove: () => void;
}) {
  return (
    <div className="relative p-4 bg-slate-50 rounded-xl border border-slate-200 space-y-3">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="absolute top-2 right-2 h-7 w-7 text-slate-400 hover:text-destructive hover:bg-destructive/10"
        onClick={onRemove}
      >
        <Trash2 className="w-3.5 h-3.5" />
      </Button>

      {/* Row 1: Day + Room */}
      <div className="grid grid-cols-2 gap-3 pr-6">
        <FormField
          control={control}
          name={`${namePrefix}.${index}.day`}
          render={({ field }) => (
            <FormItem className="space-y-1">
              <FormLabel className="text-xs text-slate-500">Day</FormLabel>
              <Select onValueChange={field.onChange} value={field.value}>
                <FormControl>
                  <SelectTrigger className="h-9 bg-white text-sm">
                    <SelectValue placeholder="Select day" />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  {DAYS.map((day) => (
                    <SelectItem key={day} value={day}>
                      {day}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={control}
          name={`${namePrefix}.${index}.room`}
          render={({ field }) => (
            <FormItem className="space-y-1">
              <FormLabel className="text-xs text-slate-500">Room</FormLabel>
              <FormControl>
                <Input
                  placeholder="e.g. Q3212"
                  className="h-9 bg-white text-sm"
                  {...field}
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
      </div>

      {/* Row 2: Start Time + End Time */}
      <div className="grid grid-cols-2 gap-3">
        <FormField
          control={control}
          name={`${namePrefix}.${index}.startTime`}
          render={({ field }) => {
            const { hour, minute, period } = parseTimeValue(field.value);
            const update = (h: string, m: string, p: string) =>
              field.onChange(`${h || "12"}:${m || "00"} ${p || "AM"}`);
            return (
              <FormItem className="space-y-1">
                <FormLabel className="text-xs text-slate-500">Start Time</FormLabel>
                <div className="flex items-center gap-1">
                  <Select value={hour} onValueChange={(v) => update(v, minute, period)}>
                    <FormControl>
                      <SelectTrigger className="h-9 bg-white text-sm w-[60px] px-2">
                        <SelectValue placeholder="HH" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>{HOURS.map(h => <SelectItem key={h} value={h}>{h}</SelectItem>)}</SelectContent>
                  </Select>
                  <span className="text-slate-400 text-sm font-medium">:</span>
                  <Select value={minute} onValueChange={(v) => update(hour, v, period)}>
                    <FormControl>
                      <SelectTrigger className="h-9 bg-white text-sm w-[60px] px-2">
                        <SelectValue placeholder="MM" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>{MINUTES.map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)}</SelectContent>
                  </Select>
                  <Select value={period} onValueChange={(v) => update(hour, minute, v)}>
                    <FormControl>
                      <SelectTrigger className="h-9 bg-white text-sm w-[68px] px-2">
                        <SelectValue placeholder="AM" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="AM">AM</SelectItem>
                      <SelectItem value="PM">PM</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <FormMessage />
              </FormItem>
            );
          }}
        />
        <FormField
          control={control}
          name={`${namePrefix}.${index}.endTime`}
          render={({ field }) => {
            const { hour, minute, period } = parseTimeValue(field.value);
            const update = (h: string, m: string, p: string) =>
              field.onChange(`${h || "12"}:${m || "00"} ${p || "AM"}`);
            return (
              <FormItem className="space-y-1">
                <FormLabel className="text-xs text-slate-500">End Time</FormLabel>
                <div className="flex items-center gap-1">
                  <Select value={hour} onValueChange={(v) => update(v, minute, period)}>
                    <FormControl>
                      <SelectTrigger className="h-9 bg-white text-sm w-[60px] px-2">
                        <SelectValue placeholder="HH" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>{HOURS.map(h => <SelectItem key={h} value={h}>{h}</SelectItem>)}</SelectContent>
                  </Select>
                  <span className="text-slate-400 text-sm font-medium">:</span>
                  <Select value={minute} onValueChange={(v) => update(hour, v, period)}>
                    <FormControl>
                      <SelectTrigger className="h-9 bg-white text-sm w-[60px] px-2">
                        <SelectValue placeholder="MM" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>{MINUTES.map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)}</SelectContent>
                  </Select>
                  <Select value={period} onValueChange={(v) => update(hour, minute, v)}>
                    <FormControl>
                      <SelectTrigger className="h-9 bg-white text-sm w-[68px] px-2">
                        <SelectValue placeholder="AM" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="AM">AM</SelectItem>
                      <SelectItem value="PM">PM</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <FormMessage />
              </FormItem>
            );
          }}
        />
      </div>
    </div>
  );
}

// ── Edit Schedule Dialog ──

function EditScheduleDialog({
  subject,
  open,
  onOpenChange,
  onSave,
  isSaving,
}: {
  subject: any;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (data: { subjectId: number; schedules: { day: string; startTime: string; endTime: string; room?: string }[] }) => void;
  isSaving: boolean;
}) {
  const form = useForm<EditScheduleFormValues>({
    resolver: zodResolver(editScheduleSchema),
    defaultValues: {
      schedules: (subject?.schedules || []).map((s: any) => ({
        day: s.day || "",
        startTime: s.startTime || "",
        endTime: s.endTime || "",
        room: s.room || "",
      })),
    },
  });

  const { fields, append, remove } = useFieldArray({
    control: form.control,
    name: "schedules",
  });

  function onSubmit(values: EditScheduleFormValues) {
    onSave({ subjectId: subject.id, schedules: values.schedules });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[560px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Edit Schedule — {subject?.name}</DialogTitle>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <div className="space-y-3">
              {fields.map((field, index) => (
                <ScheduleEntryRow
                  key={field.id}
                  index={index}
                  control={form.control}
                  namePrefix="schedules"
                  onRemove={() => remove(index)}
                />
              ))}

              <Button
                type="button"
                variant="outline"
                className="w-full rounded-xl border-dashed gap-2"
                onClick={() =>
                  append({ day: "", startTime: "", endTime: "", room: "" })
                }
              >
                <Plus className="w-4 h-4" /> Add Schedule
              </Button>
            </div>

            <Button type="submit" className="w-full" disabled={isSaving}>
              {isSaving ? <Loader2 className="animate-spin w-4 h-4 mr-2" /> : null}
              Save Changes
            </Button>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}

// ── Schedule Overview Panel ──

function SchedulePanel({ subjects, isLoading }: { subjects: any[]; isLoading: boolean }) {
  const today = DAYS[new Date().getDay() === 0 ? 6 : new Date().getDay() - 1]; // Sunday=6, Mon=0

  // Build a flat list of all schedule entries across all subjects
  const allEntries: { courseCode: string; day: string; startTime: string; endTime: string; room: string }[] = [];
  for (const subj of subjects) {
    if (Array.isArray(subj.schedules)) {
      for (const s of subj.schedules) {
        allEntries.push({
          courseCode: subj.courseCode,
          day: s.day,
          startTime: s.startTime,
          endTime: s.endTime,
          room: s.room || "",
        });
      }
    }
  }

  const todayEntries = allEntries.filter(e => e.day === today);

  // Group by day for weekly view (only days that have entries, ordered by DAYS array)
  const weeklyGrouped: { day: string; entries: typeof allEntries }[] = [];
  for (const day of DAYS) {
    const dayEntries = allEntries.filter(e => e.day === day);
    if (dayEntries.length > 0) {
      weeklyGrouped.push({ day, entries: dayEntries });
    }
  }

  if (isLoading) {
    return (
      <Card className="border-slate-200">
        <CardContent className="p-6 space-y-4">
          {[1, 2, 3].map(i => (
            <div key={i} className="h-12 bg-slate-100 rounded-xl animate-pulse" />
          ))}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-slate-200 sticky top-8">
      <CardContent className="p-6 space-y-6">
        {/* Today's Schedule */}
        <div>
          <div className="flex items-center gap-2 mb-1">
            <div className="w-7 h-7 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center">
              <CalendarCheck className="w-4 h-4" />
            </div>
            <h2 className="text-base font-bold font-display text-slate-900">Today's Schedule <span className="font-normal text-slate-400">({today})</span></h2>
          </div>
          {todayEntries.length > 0 ? (
            <div className="space-y-2">
              {todayEntries.map((entry, i) => (
                <ScheduleRow key={i} entry={entry} />
              ))}
            </div>
          ) : (
            <p className="text-sm text-slate-400 italic py-4 text-center">No classes today</p>
          )}
        </div>

        {/* Divider */}
        <hr className="border-slate-100" />

        {/* Weekly Schedule */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <div className="w-7 h-7 rounded-lg bg-indigo-50 text-indigo-600 flex items-center justify-center">
              <CalendarDays className="w-4 h-4" />
            </div>
            <h2 className="text-base font-bold font-display text-slate-900">Weekly Schedule</h2>
          </div>
          {weeklyGrouped.length > 0 ? (
            <div className="space-y-4">
              {weeklyGrouped.map(group => (
                <div key={group.day}>
                  <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 ml-1">{group.day}</h3>
                  <div className="space-y-2">
                    {group.entries.map((entry, i) => (
                      <ScheduleRow key={i} entry={entry} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-slate-400 italic py-4 text-center">No schedules set</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function ScheduleRow({ entry }: { entry: { courseCode: string; startTime: string; endTime: string; room: string } }) {
  return (
    <div className="flex items-center justify-between bg-slate-50 rounded-xl px-4 py-3 text-sm border border-slate-100">
      <span className="font-semibold text-slate-700 truncate">
        {entry.courseCode}
      </span>
      <span className="text-slate-500 whitespace-nowrap ml-3 text-xs">
        {entry.startTime} - {entry.endTime}
      </span>
      {entry.room && (
        <span className="text-slate-400 whitespace-nowrap ml-2 text-xs">{entry.room}</span>
      )}
    </div>
  );
}

// ── Main Page ──

export default function ClassesPage() {
  const { subjects, isLoading, createSubject, isCreating, deleteSubject, isDeleting, updateSchedules, isUpdatingSchedules } = useSubjects();
  const [isOpen, setIsOpen] = useState(false);
  const [editSubject, setEditSubject] = useState<any>(null);

  const form = useForm<SubjectFormValues>({
    resolver: zodResolver(subjectSchema),
    defaultValues: { name: "", courseCode: "", section: "", schedule: [] },
  });

  const { fields, append, remove } = useFieldArray({
    control: form.control,
    name: "schedule",
  });

  function onSubmit(values: SubjectFormValues) {
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
          <Dialog open={isOpen} onOpenChange={(open) => {
            setIsOpen(open);
            if (!open) form.reset();
          }}>
            <DialogTrigger asChild>
              <Button className="rounded-xl shadow-lg shadow-primary/20 gap-2">
                <Plus className="w-4 h-4" /> Add Class
              </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-[560px] max-h-[90vh] overflow-y-auto">
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

                  {/* Schedule Section */}
                  <div className="space-y-3">
                    <FormLabel className="text-sm font-medium">Schedule</FormLabel>

                    {fields.map((field, index) => (
                      <ScheduleEntryRow
                        key={field.id}
                        index={index}
                        control={form.control}
                        namePrefix="schedule"
                        onRemove={() => remove(index)}
                      />
                    ))}

                    <Button
                      type="button"
                      variant="outline"
                      className="w-full rounded-xl border-dashed gap-2"
                      onClick={() =>
                        append({ day: "", startTime: "", endTime: "", room: "" })
                      }
                    >
                      <Plus className="w-4 h-4" /> Add Schedule
                    </Button>
                  </div>

                  <Button type="submit" className="w-full" disabled={isCreating}>
                    {isCreating ? <Loader2 className="animate-spin w-4 h-4 mr-2" /> : null}
                    Create Class
                  </Button>
                </form>
              </Form>
            </DialogContent>
          </Dialog>
        </div>

        {/* Two-column layout: Schedule Panel (left) + Class Cards (right) */}
        <div className="flex gap-6">
          {/* ── Left: Schedule Overview Panel ── */}
          <div className="w-96 flex-shrink-0 space-y-6">
            <SchedulePanel subjects={subjects || []} isLoading={isLoading} />
          </div>

          {/* ── Right: Class Cards ── */}
          <div className="flex-1 min-w-0">
            {isLoading ? (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
                {[1, 2, 3].map(i => <div key={i} className="h-40 bg-slate-100 rounded-2xl animate-pulse"></div>)}
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
                {subjects?.map((subject: any) => (
                  <Card key={subject.id} className="group hover:shadow-lg transition-all duration-300 border-slate-200">
                    <CardContent className="p-6">
                      <div className="flex justify-between items-start mb-4">
                        <div className="w-12 h-12 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center group-hover:bg-blue-600 group-hover:text-white transition-colors">
                          <BookOpen className="w-6 h-6" />
                        </div>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 text-slate-400 hover:text-slate-600"
                            >
                              <MoreVertical className="w-4 h-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="w-44">
                            <DropdownMenuItem
                              className="gap-2 cursor-pointer"
                              onClick={() => setEditSubject(subject)}
                            >
                              <Pencil className="w-4 h-4" />
                              Edit Schedule
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              className="gap-2 cursor-pointer text-destructive focus:text-destructive"
                              onClick={() => {
                                if (confirm("Are you sure you want to delete this class?")) {
                                  deleteSubject(subject.id);
                                }
                              }}
                            >
                              <Trash2 className="w-4 h-4" />
                              Delete Subject
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                      <h3 className="font-bold font-display text-lg text-slate-900">{subject.name}</h3>
                      <div className="flex gap-2 text-sm text-slate-500 mt-1">
                        <span className="font-mono bg-slate-100 px-2 py-0.5 rounded text-xs">{subject.courseCode}</span>
                        <span>•</span>
                        <span>{subject.section}</span>
                      </div>
                      {/* Schedule display */}
                      {Array.isArray(subject.schedules) && subject.schedules.length > 0 && (
                        <div className="mt-4 pt-4 border-t border-slate-100 space-y-1.5">
                          {subject.schedules.map((entry: any, idx: number) => (
                            <div key={idx} className="flex items-center gap-3 text-xs text-slate-500">
                              <span className="flex items-center gap-1">
                                <Calendar className="w-3 h-3 text-slate-400" />
                                {entry.day}
                              </span>
                              <span className="flex items-center gap-1">
                                <Clock className="w-3 h-3 text-slate-400" />
                                {entry.startTime} - {entry.endTime}
                              </span>
                              {entry.room && (
                                <span className="flex items-center gap-1">
                                  <MapPin className="w-3 h-3 text-slate-400" />
                                  {entry.room}
                                </span>
                              )}
                            </div>
                          ))}
                        </div>
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
        </div>
      </div>

      {/* Edit Schedule Dialog */}
      {editSubject && (
        <EditScheduleDialog
          key={editSubject.id}
          subject={editSubject}
          open={!!editSubject}
          onOpenChange={(open) => {
            if (!open) setEditSubject(null);
          }}
          onSave={(data) => {
            updateSchedules(data, {
              onSuccess: () => setEditSubject(null),
            });
          }}
          isSaving={isUpdatingSchedules}
        />
      )}
    </SidebarLayout>
  );
}
