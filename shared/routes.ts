import { z } from 'zod';
import { insertUserSchema, insertSubjectSchema, users, subjects, sessions } from './schema';

export const errorSchemas = {
  validation: z.object({
    message: z.string(),
    field: z.string().optional(),
  }),
  notFound: z.object({
    message: z.string(),
  }),
  internal: z.object({
    message: z.string(),
  }),
  unauthorized: z.object({
    message: z.string(),
  }),
};

export const api = {
  auth: {
    login: {
      method: 'POST' as const,
      path: '/api/login' as const,
      input: z.object({ username: z.string(), password: z.string() }),
      responses: {
        200: z.custom<typeof users.$inferSelect>(),
        401: errorSchemas.unauthorized,
      },
    },
    register: {
      method: 'POST' as const,
      path: '/api/register' as const,
      input: insertUserSchema,
      responses: {
        201: z.custom<typeof users.$inferSelect>(),
        400: errorSchemas.validation,
      },
    },
    logout: {
      method: 'POST' as const,
      path: '/api/logout' as const,
      responses: {
        200: z.void(),
      },
    },
    me: {
      method: 'GET' as const,
      path: '/api/user' as const,
      responses: {
        200: z.custom<typeof users.$inferSelect>(),
        401: errorSchemas.unauthorized,
      },
    },
  },
  subjects: {
    list: {
      method: 'GET' as const,
      path: '/api/subjects' as const,
      responses: {
        200: z.array(z.custom<typeof subjects.$inferSelect>()),
      },
    },
    create: {
      method: 'POST' as const,
      path: '/api/subjects' as const,
      input: insertSubjectSchema.omit({ teacherId: true }),
      responses: {
        201: z.custom<typeof subjects.$inferSelect>(),
        400: errorSchemas.validation,
      },
    },
    delete: {
      method: 'DELETE' as const,
      path: '/api/subjects/:id' as const,
      responses: {
        204: z.void(),
        404: errorSchemas.notFound,
      },
    },
  },
  sessions: {
    list: {
      method: 'GET' as const,
      path: '/api/sessions' as const,
      responses: {
        200: z.array(z.custom<typeof sessions.$inferSelect & { subject: typeof subjects.$inferSelect }>()),
      },
    },
    start: {
      method: 'POST' as const,
      path: '/api/sessions' as const,
      input: z.object({ subjectId: z.number() }),
      responses: {
        201: z.custom<typeof sessions.$inferSelect>(),
      },
    },
    end: {
      method: 'POST' as const,
      path: '/api/sessions/:id/end' as const,
      input: z.object({ summaryStats: z.any() }),
      responses: {
        200: z.custom<typeof sessions.$inferSelect>(),
      },
    },
  },
  stats: {
    dashboard: {
      method: 'GET' as const,
      path: '/api/stats/dashboard' as const,
      responses: {
        200: z.object({
          totalSessions: z.number(),
          avgAttentionScore: z.number(),
          totalStudents: z.number(),
        }),
      },
    },
  },
};

export function buildUrl(path: string, params?: Record<string, string | number>): string {
  let url = path;
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (url.includes(`:${key}`)) {
        url = url.replace(`:${key}`, String(value));
      }
    });
  }
  return url;
}
