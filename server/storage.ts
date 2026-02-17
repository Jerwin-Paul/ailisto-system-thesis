import { db } from "./db";
import { users, subjects, schedules, sessions, type User, type InsertUser, type Subject, type InsertSubject, type Schedule, type Session } from "@shared/schema";
import { eq, desc } from "drizzle-orm";

import session from "express-session";
import createMemoryStore from "memorystore";

const MemoryStore = createMemoryStore(session);

export interface IStorage {
  // User
  getUser(id: number): Promise<User | undefined>;
  getUserByEmail(email: string): Promise<User | undefined>;
  createUser(user: InsertUser): Promise<User>;
  updateUserPassword(id: number, hashedPassword: string): Promise<void>;

  // Subject
  getSubjects(teacherId: number): Promise<(Subject & { schedules: Schedule[] })[]>;
  createSubject(subject: InsertSubject, scheduleEntries: { day: string; startTime: string; endTime: string; room?: string }[]): Promise<Subject & { schedules: Schedule[] }>;
  deleteSubject(id: number): Promise<void>;

  // Schedule
  addSchedule(subjectId: number, entry: { day: string; startTime: string; endTime: string; room?: string }): Promise<Schedule>;
  updateSchedule(id: number, entry: { day: string; startTime: string; endTime: string; room?: string }): Promise<Schedule>;
  deleteSchedule(id: number): Promise<void>;
  updateSubjectSchedules(subjectId: number, entries: { id?: number; day: string; startTime: string; endTime: string; room?: string }[]): Promise<Schedule[]>;

  // Session
  getSessions(teacherId: number): Promise<(Session & { subject: Subject | null })[]>;
  createSession(session: { subjectId: number }): Promise<Session>;
  endSession(id: number, summaryStats: any): Promise<Session>;

  sessionStore: session.Store;
}

export class DatabaseStorage implements IStorage {
  sessionStore: session.Store;

  constructor() {
    this.sessionStore = new MemoryStore({
      checkPeriod: 86400000,
    });
  }
  async getUser(id: number): Promise<User | undefined> {
    const [user] = await db.select().from(users).where(eq(users.id, id));
    return user;
  }

  async getUserByEmail(email: string): Promise<User | undefined> {
    const [user] = await db.select().from(users).where(eq(users.email, email));
    return user;
  }

  async createUser(user: InsertUser): Promise<User> {
    const [newUser] = await db.insert(users).values(user).returning();
    return newUser;
  }

  async updateUserPassword(id: number, hashedPassword: string): Promise<void> {
    await db.update(users).set({ password: hashedPassword }).where(eq(users.id, id));
  }

  async getSubjects(teacherId: number): Promise<(Subject & { schedules: Schedule[] })[]> {
    const subjectRows = await db.select().from(subjects).where(eq(subjects.teacherId, teacherId));

    // Fetch schedules for all subjects
    const result: (Subject & { schedules: Schedule[] })[] = [];
    for (const subject of subjectRows) {
      const subjectSchedules = await db.select().from(schedules).where(eq(schedules.subjectId, subject.id));
      result.push({ ...subject, schedules: subjectSchedules });
    }
    return result;
  }

  async createSubject(
    subject: InsertSubject,
    scheduleEntries: { day: string; startTime: string; endTime: string; room?: string }[]
  ): Promise<Subject & { schedules: Schedule[] }> {
    const [newSubject] = await db.insert(subjects).values(subject).returning();

    const newSchedules: Schedule[] = [];
    if (scheduleEntries.length > 0) {
      const rows = await db.insert(schedules).values(
        scheduleEntries.map(entry => ({
          subjectId: newSubject.id,
          day: entry.day,
          startTime: entry.startTime,
          endTime: entry.endTime,
          room: entry.room || "",
        }))
      ).returning();
      newSchedules.push(...rows);
    }

    return { ...newSubject, schedules: newSchedules };
  }

  async deleteSubject(id: number): Promise<void> {
    // Delete schedules first, then subject
    await db.delete(schedules).where(eq(schedules.subjectId, id));
    await db.delete(subjects).where(eq(subjects.id, id));
  }

  async addSchedule(subjectId: number, entry: { day: string; startTime: string; endTime: string; room?: string }): Promise<Schedule> {
    const [row] = await db.insert(schedules).values({
      subjectId,
      day: entry.day,
      startTime: entry.startTime,
      endTime: entry.endTime,
      room: entry.room || "",
    }).returning();
    return row;
  }

  async updateSchedule(id: number, entry: { day: string; startTime: string; endTime: string; room?: string }): Promise<Schedule> {
    const [row] = await db.update(schedules).set({
      day: entry.day,
      startTime: entry.startTime,
      endTime: entry.endTime,
      room: entry.room || "",
    }).where(eq(schedules.id, id)).returning();
    return row;
  }

  async deleteSchedule(id: number): Promise<void> {
    await db.delete(schedules).where(eq(schedules.id, id));
  }

  async updateSubjectSchedules(subjectId: number, entries: { id?: number; day: string; startTime: string; endTime: string; room?: string }[]): Promise<Schedule[]> {
    // Delete all existing schedules for this subject
    await db.delete(schedules).where(eq(schedules.subjectId, subjectId));

    // Insert all new/updated entries
    if (entries.length === 0) return [];
    const rows = await db.insert(schedules).values(
      entries.map(e => ({
        subjectId,
        day: e.day,
        startTime: e.startTime,
        endTime: e.endTime,
        room: e.room || "",
      }))
    ).returning();
    return rows;
  }

  async getSessions(teacherId: number): Promise<(Session & { subject: Subject | null })[]> {
    const rows = await db.select({
      session: sessions,
      subject: subjects,
    })
      .from(sessions)
      .innerJoin(subjects, eq(sessions.subjectId, subjects.id))
      .where(eq(subjects.teacherId, teacherId))
      .orderBy(desc(sessions.startTime));

    return rows.map(r => ({ ...r.session, subject: r.subject }));
  }

  async createSession(session: { subjectId: number }): Promise<Session> {
    const [newSession] = await db.insert(sessions).values({
      subjectId: session.subjectId,
      status: "active",
      startTime: new Date(),
    }).returning();
    return newSession;
  }

  async endSession(id: number, summaryStats: any): Promise<Session> {
    const [updated] = await db.update(sessions)
      .set({ status: "completed", endTime: new Date(), summaryStats })
      .where(eq(sessions.id, id))
      .returning();
    return updated;
  }
}

export const storage = new DatabaseStorage();
