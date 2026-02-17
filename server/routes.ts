import type { Express } from "express";
import { createServer, type Server } from "http";
import { storage } from "./storage";
import { setupAuth } from "./auth";
import { api } from "@shared/routes";
import { z } from "zod";

export async function registerRoutes(
  httpServer: Server,
  app: Express
): Promise<Server> {
  // Setup Auth
  setupAuth(app);

  // Subjects
  app.get(api.subjects.list.path, async (req, res) => {
    if (!req.isAuthenticated()) return res.sendStatus(401);
    const subjects = await storage.getSubjects(req.user.id);
    res.json(subjects);
  });

  app.post(api.subjects.create.path, async (req, res) => {
    if (!req.isAuthenticated()) return res.sendStatus(401);
    try {
      const input = api.subjects.create.input.parse(req.body);
      const { schedule, ...subjectData } = input;
      const subject = await storage.createSubject(
        { ...subjectData, teacherId: req.user.id },
        schedule || []
      );
      res.status(201).json(subject);
    } catch (err) {
      console.error("Subject creation error:", err);
      if (err instanceof z.ZodError) res.status(400).json({ message: err.errors[0].message });
      else res.status(500).json({ message: "Internal Server Error" });
    }
  });

  app.delete(api.subjects.delete.path, async (req, res) => {
    if (!req.isAuthenticated()) return res.sendStatus(401);
    await storage.deleteSubject(Number(req.params.id));
    res.sendStatus(204);
  });

  // Schedule management
  app.put("/api/subjects/:id/schedules", async (req, res) => {
    if (!req.isAuthenticated()) return res.sendStatus(401);
    try {
      const subjectId = Number(req.params.id);
      const { schedules: entries } = req.body as { schedules: { id?: number; day: string; startTime: string; endTime: string; room?: string }[] };
      const result = await storage.updateSubjectSchedules(subjectId, entries || []);
      res.json(result);
    } catch (err) {
      console.error("Schedule update error:", err);
      res.status(500).json({ message: "Internal Server Error" });
    }
  });

  // Sessions
  app.get(api.sessions.list.path, async (req, res) => {
    if (!req.isAuthenticated()) return res.sendStatus(401);
    const sessions = await storage.getSessions(req.user.id);
    res.json(sessions);
  });

  app.post(api.sessions.start.path, async (req, res) => {
    if (!req.isAuthenticated()) return res.sendStatus(401);
    const input = api.sessions.start.input.parse(req.body);
    const session = await storage.createSession(input);
    res.status(201).json(session);
  });

  app.post(api.sessions.end.path, async (req, res) => {
    if (!req.isAuthenticated()) return res.sendStatus(401);
    const input = api.sessions.end.input.parse(req.body);
    const session = await storage.endSession(Number(req.params.id), input.summaryStats);
    res.json(session);
  });

  // Stats (Mock)
  app.get(api.stats.dashboard.path, async (req, res) => {
    if (!req.isAuthenticated()) return res.sendStatus(401);
    res.json({
      totalSessions: 12,
      avgAttentionScore: 85,
      totalStudents: 150,
    });
  });

  return httpServer;
}

async function seed() {
  const existingUser = await storage.getUserByEmail("teacher@school.com");
  if (!existingUser) {
    const { scrypt, randomBytes } = await import("crypto");
    const { promisify } = await import("util");
    const scryptAsync = promisify(scrypt);

    const salt = randomBytes(16).toString("hex");
    const buf = (await scryptAsync("password123", salt, 64)) as Buffer;
    const hashedPassword = `${buf.toString("hex")}.${salt}`;

    const user = await storage.createUser({
      email: "teacher@school.com",
      password: hashedPassword,
      firstName: "Jane",
      lastName: "Doe",
      role: "teacher"
    });

    // Create subjects with schedules
    const sub1 = await storage.createSubject(
      { teacherId: user.id, name: "Mathematics", courseCode: "MATH101", section: "Grade 5 - A" },
      [
        { day: "Monday", startTime: "10:00 AM", endTime: "11:30 AM", room: "Room 101" },
        { day: "Wednesday", startTime: "10:00 AM", endTime: "11:30 AM", room: "Room 101" },
      ]
    );

    await storage.createSubject(
      { teacherId: user.id, name: "Science", courseCode: "SCI101", section: "Grade 5 - B" },
      [
        { day: "Tuesday", startTime: "01:00 PM", endTime: "02:30 PM", room: "Lab 201" },
        { day: "Thursday", startTime: "01:00 PM", endTime: "02:30 PM", room: "Lab 201" },
      ]
    );

    // Create past sessions
    await storage.createSession({ subjectId: sub1.id });
  }
}

seed().catch(console.error);
