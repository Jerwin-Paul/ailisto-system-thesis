import { db } from "./db";
import { users, subjects, sessions, type User, type InsertUser, type Subject, type InsertSubject, type Session } from "@shared/schema";
import { eq, desc } from "drizzle-orm";

import session from "express-session";
import createMemoryStore from "memorystore";

const MemoryStore = createMemoryStore(session);

export interface IStorage {
  // User
  getUser(id: number): Promise<User | undefined>;
  getUserByUsername(username: string): Promise<User | undefined>;
  createUser(user: InsertUser): Promise<User>;
  
  // Subject
  getSubjects(teacherId: number): Promise<Subject[]>;
  createSubject(subject: InsertSubject): Promise<Subject>;
  deleteSubject(id: number): Promise<void>;

  // Session
  getSessions(teacherId: number): Promise<(Session & { subject: Subject | null })[]>; // Fixed type
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

  async getUserByUsername(username: string): Promise<User | undefined> {
    const [user] = await db.select().from(users).where(eq(users.username, username));
    return user;
  }

  async createUser(user: InsertUser): Promise<User> {
    const [newUser] = await db.insert(users).values(user).returning();
    return newUser;
  }

  async getSubjects(teacherId: number): Promise<Subject[]> {
    return await db.select().from(subjects).where(eq(subjects.teacherId, teacherId));
  }

  async createSubject(subject: InsertSubject): Promise<Subject> {
    const [newSubject] = await db.insert(subjects).values(subject).returning();
    return newSubject;
  }

  async deleteSubject(id: number): Promise<void> {
    await db.delete(subjects).where(eq(subjects.id, id));
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
