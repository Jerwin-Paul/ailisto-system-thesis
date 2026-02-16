import { pgTable, text, serial, integer, boolean, timestamp, jsonb } from "drizzle-orm/pg-core";
import { relations } from "drizzle-orm";
import { createInsertSchema } from "drizzle-zod";
import { z } from "zod";

// === TABLE DEFINITIONS ===

export const users = pgTable("users", {
  id: serial("id").primaryKey(),
  email: text("email").notNull().unique(),
  password: text("password").notNull(),
  firstName: text("first_name").notNull(),
  lastName: text("last_name").notNull(),
  role: text("role").notNull().default("teacher"), // 'teacher' | 'admin'
  createdAt: timestamp("created_at").defaultNow(),
});

export const subjects = pgTable("subjects", {
  id: serial("id").primaryKey(),
  teacherId: integer("teacher_id").notNull(), // FK to users
  name: text("name").notNull(),
  courseCode: text("course_code").notNull(),
  section: text("section").notNull(),
  schedule: text("schedule"), // E.g., "Mon 10-12"
});

export const sessions = pgTable("sessions", {
  id: serial("id").primaryKey(),
  subjectId: integer("subject_id").notNull(), // FK to subjects
  startTime: timestamp("start_time").defaultNow(),
  endTime: timestamp("end_time"),
  status: text("status").notNull().default("active"), // 'active' | 'completed'
  summaryStats: jsonb("summary_stats"), // Store session summary
});

// === RELATIONS ===

export const usersRelations = relations(users, ({ many }) => ({
  subjects: many(subjects),
}));

export const subjectsRelations = relations(subjects, ({ one, many }) => ({
  teacher: one(users, {
    fields: [subjects.teacherId],
    references: [users.id],
  }),
  sessions: many(sessions),
}));

export const sessionsRelations = relations(sessions, ({ one }) => ({
  subject: one(subjects, {
    fields: [sessions.subjectId],
    references: [subjects.id],
  }),
}));

// === BASE SCHEMAS ===

export const insertUserSchema = createInsertSchema(users).omit({ id: true, createdAt: true });
export const insertSubjectSchema = createInsertSchema(subjects).omit({ id: true });
export const insertSessionSchema = createInsertSchema(sessions).omit({ id: true, startTime: true, endTime: true, status: true, summaryStats: true });

// === EXPLICIT API CONTRACT TYPES ===

export type User = typeof users.$inferSelect;
export type InsertUser = z.infer<typeof insertUserSchema>;
export type Subject = typeof subjects.$inferSelect;
export type InsertSubject = z.infer<typeof insertSubjectSchema>;
export type Session = typeof sessions.$inferSelect;

// Auth
export type LoginRequest = { email: string; password: string };
export type RegisterRequest = InsertUser;

// Subjects
export type CreateSubjectRequest = Omit<InsertSubject, "teacherId">;

// Sessions
export type StartSessionRequest = { subjectId: number };
export type EndSessionRequest = { summaryStats: any };

// Stats
export interface DashboardStats {
  totalSessions: number;
  avgAttentionScore: number;
  totalStudents: number;
  recentActivity: Session[];
}
