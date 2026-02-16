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
      const subject = await storage.createSubject({ ...input, teacherId: req.user.id });
      res.status(201).json(subject);
    } catch (err) {
      if (err instanceof z.ZodError) res.status(400).json({ message: err.errors[0].message });
      else res.status(500).json({ message: "Internal Server Error" });
    }
  });

  app.delete(api.subjects.delete.path, async (req, res) => {
    if (!req.isAuthenticated()) return res.sendStatus(401);
    await storage.deleteSubject(Number(req.params.id));
    res.sendStatus(204);
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
  const existingUser = await storage.getUserByUsername("teacher@school.com");
  if (!existingUser) {
    const { scrypt, randomBytes } = await import("crypto");
    const { promisify } = await import("util");
    const scryptAsync = promisify(scrypt);
    
    const salt = randomBytes(16).toString("hex");
    const buf = (await scryptAsync("password123", salt, 64)) as Buffer;
    const hashedPassword = `${buf.toString("hex")}.${salt}`;
    
    const user = await storage.createUser({
      username: "teacher@school.com",
      password: hashedPassword,
      firstName: "Jane",
      lastName: "Doe",
      role: "teacher"
    });
    
    // Create subjects
    const sub1 = await storage.createSubject({
      teacherId: user.id,
      name: "Mathematics",
      courseCode: "MATH101",
      section: "Grade 5 - A",
      schedule: "Mon/Wed 10:00 AM"
    });
    
    await storage.createSubject({
      teacherId: user.id,
      name: "Science",
      courseCode: "SCI101",
      section: "Grade 5 - B",
      schedule: "Tue/Thu 1:00 PM"
    });

    // Create past sessions
    await storage.createSession({ subjectId: sub1.id });
    // We can't easily force timestamp in createSession without modifying storage, 
    // but this is enough to have some data.
  }
}

seed().catch(console.error);
