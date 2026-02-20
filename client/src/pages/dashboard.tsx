import { SidebarLayout } from "@/components/layout-sidebar";
import { useAuth } from "@/hooks/use-auth";
import { useSessions } from "@/hooks/use-sessions";
import { useSubjects } from "@/hooks/use-subjects";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Link } from "wouter";
import {
  Clock,
  Activity,
  ArrowRight,
  Play,
  Calendar,
  BookOpen,
} from "lucide-react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { format } from "date-fns";

export default function Dashboard() {
  const { user } = useAuth();
  const { dashboardStats, isLoadingStats, sessions } = useSessions();
  const { subjects } = useSubjects();

  // Mock data for charts if API data is thin
  const chartData = [
    { name: 'Mon', value: 85 },
    { name: 'Tue', value: 78 },
    { name: 'Wed', value: 92 },
    { name: 'Thu', value: 88 },
    { name: 'Fri', value: 76 },
  ];

  // Build per-class attention stats
  const perClassStats: { id: number; name: string; section: string; courseCode: string; avgAttention: number; sessionCount: number }[] = [];
  if (subjects && sessions) {
    for (const subj of subjects as any[]) {
      const classSessions = (sessions as any[]).filter((s: any) => s.subjectId === subj.id);
      const attentionValues = classSessions
        .map((s: any) => s.summaryStats?.avgAttention)
        .filter((v: any) => typeof v === 'number' && !isNaN(v));
      const avg = attentionValues.length > 0
        ? Math.round(attentionValues.reduce((a: number, b: number) => a + b, 0) / attentionValues.length)
        : 0;
      perClassStats.push({
        id: subj.id,
        name: subj.name,
        section: subj.section,
        courseCode: subj.courseCode,
        avgAttention: avg,
        sessionCount: classSessions.length,
      });
    }
  }

  if (isLoadingStats) {
    return (
      <SidebarLayout>
        <div className="flex items-center justify-center h-96">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
        </div>
      </SidebarLayout>
    );
  }

  return (
    <SidebarLayout>
      <div className="space-y-8">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h2 className="text-3xl font-bold font-display text-slate-900">
              Good morning, {user?.lastName}!
            </h2>
            <p className="text-slate-500 mt-1">Here's what's happening in your classes.</p>
          </div>
          <Link href="/live">
            <Button className="h-12 px-6 rounded-xl shadow-lg shadow-primary/25 hover:shadow-xl hover:shadow-primary/30 transition-all gap-2">
              <Play className="w-4 h-4 fill-current" />
              Start Live Session
            </Button>
          </Link>
        </div>

        {/* Stats Grid — 2 cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Card className="border-none shadow-md hover:shadow-lg transition-all duration-300 group">
            <CardContent className="p-6">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 rounded-2xl bg-blue-100 text-blue-600 flex items-center justify-center group-hover:scale-110 transition-transform">
                  <Activity className="w-6 h-6" />
                </div>
                <div>
                  <p className="text-sm font-medium text-slate-500">Avg. Attention</p>
                  <h3 className="text-2xl font-bold font-display text-slate-900">
                    {dashboardStats?.avgAttentionScore || 0}%
                  </h3>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="border-none shadow-md hover:shadow-lg transition-all duration-300 group">
            <CardContent className="p-6">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 rounded-2xl bg-indigo-100 text-indigo-600 flex items-center justify-center group-hover:scale-110 transition-transform">
                  <Clock className="w-6 h-6" />
                </div>
                <div>
                  <p className="text-sm font-medium text-slate-500">Total Sessions</p>
                  <h3 className="text-2xl font-bold font-display text-slate-900">
                    {dashboardStats?.totalSessions || 0}
                  </h3>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Attention by Class */}
        <Card className="border-slate-100 shadow-sm">
          <CardHeader>
            <CardTitle className="font-display text-lg flex items-center gap-2">
              <BookOpen className="w-5 h-5 text-primary" />
              Attention by Class
            </CardTitle>
          </CardHeader>
          <CardContent>
            {perClassStats.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {perClassStats.map((cls) => {
                  const color = cls.avgAttention > 80 ? 'emerald' : cls.avgAttention > 60 ? 'amber' : cls.avgAttention > 0 ? 'red' : 'slate';
                  return (
                    <div key={cls.id} className="bg-slate-50 rounded-xl p-4 border border-slate-100 hover:border-slate-200 transition-colors">
                      <div className="flex items-center justify-between mb-2">
                        <div className="min-w-0">
                          <p className="text-sm font-semibold text-slate-800 truncate">{cls.courseCode} - {cls.section}</p>
                          <p className="text-xs text-slate-400 truncate">{cls.name}</p>
                        </div>
                        <span className={`text-lg font-bold font-display ${color === 'emerald' ? 'text-emerald-600' :
                          color === 'amber' ? 'text-amber-500' :
                            color === 'red' ? 'text-red-500' : 'text-slate-400'
                          }`}>
                          {cls.sessionCount > 0 ? `${cls.avgAttention}%` : '—'}
                        </span>
                      </div>
                      {/* Progress bar */}
                      <div className="w-full h-2 bg-slate-200 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all duration-500 ${color === 'emerald' ? 'bg-emerald-500' :
                            color === 'amber' ? 'bg-amber-400' :
                              color === 'red' ? 'bg-red-500' : 'bg-slate-300'
                            }`}
                          style={{ width: `${cls.sessionCount > 0 ? cls.avgAttention : 0}%` }}
                        />
                      </div>
                      <p className="text-[10px] text-slate-400 mt-1.5">
                        {cls.sessionCount} session{cls.sessionCount !== 1 ? 's' : ''} recorded
                      </p>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-sm text-slate-400 italic text-center py-8">No classes found. Add classes to see per-class statistics.</p>
            )}
          </CardContent>
        </Card>

        {/* Main Content Area */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Chart Section */}
          <div className="lg:col-span-2 space-y-6">
            <Card className="border-slate-100 shadow-sm">
              <CardHeader>
                <CardTitle className="font-display text-lg">Weekly Attention Trends</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-[300px] w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={chartData}>
                      <defs>
                        <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                          <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                      <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: '#64748b' }} dy={10} />
                      <YAxis axisLine={false} tickLine={false} tick={{ fill: '#64748b' }} />
                      <Tooltip
                        contentStyle={{ backgroundColor: '#fff', borderRadius: '12px', border: '1px solid #e2e8f0', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                      />
                      <Area
                        type="monotone"
                        dataKey="value"
                        stroke="#3b82f6"
                        strokeWidth={3}
                        fillOpacity={1}
                        fill="url(#colorValue)"
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Recent Activity Sidebar */}
          <div className="space-y-6">
            <Card className="h-full border-slate-100 shadow-sm">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="font-display text-lg">Recent Sessions</CardTitle>
                <Link href="/history">
                  <Button variant="ghost" size="sm" className="text-primary hover:text-primary/80 p-0 h-auto">
                    View All <ArrowRight className="w-4 h-4 ml-1" />
                  </Button>
                </Link>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="flex items-center gap-4 p-3 rounded-xl hover:bg-slate-50 transition-colors cursor-pointer group">
                      <div className="w-10 h-10 rounded-lg bg-slate-100 flex items-center justify-center text-slate-500 group-hover:bg-primary/10 group-hover:text-primary transition-colors">
                        <Calendar className="w-5 h-5" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold text-slate-900 truncate">Science 101 - Section A</p>
                        <p className="text-xs text-slate-500">{format(new Date(), 'MMM d, yyyy • h:mm a')}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-sm font-bold text-emerald-600">85%</p>
                        <p className="text-[10px] text-slate-400">Attention</p>
                      </div>
                    </div>
                  ))}
                  {(!dashboardStats?.recentActivity || dashboardStats.recentActivity.length === 0) && (
                    <div className="text-center py-8 text-slate-400 text-sm">
                      No recent sessions found.
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </SidebarLayout>
  );
}
