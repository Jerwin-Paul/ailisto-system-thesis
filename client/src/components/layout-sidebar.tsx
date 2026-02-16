import { Link, useLocation } from "wouter";
import { useAuth } from "@/hooks/use-auth";
import {
  LayoutDashboard,
  Video,
  BookOpen,
  History,
  FileText,
  Settings,
  LogOut,
  UserCircle,
  Menu,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { useState } from "react";

export function SidebarLayout({ children }: { children: React.ReactNode }) {
  const [location] = useLocation();
  const { user, logoutMutation } = useAuth();
  const [isOpen, setIsOpen] = useState(false);

  const navigation = [
    { name: "Dashboard", href: "/", icon: LayoutDashboard },
    { name: "Live Session", href: "/live", icon: Video },
    { name: "Classes", href: "/classes", icon: BookOpen },
    { name: "History", href: "/history", icon: History },
    { name: "Reports", href: "/reports", icon: FileText },
  ];

  if (user?.role === "admin") {
    navigation.push({ name: "User Management", href: "/admin", icon: Settings });
  }

  const NavContent = () => (
    <div className="flex flex-col h-full bg-slate-50 border-r border-slate-200">
      <div className="p-6 border-b border-slate-200 bg-white">
        <h1 className="text-2xl font-bold text-primary font-display flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center text-white">
            <Video className="w-5 h-5" />
          </div>
          Ai-Listo
        </h1>
        <p className="text-xs text-muted-foreground mt-1">SSS Vilage Elementary School</p>
      </div>

      <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
        {navigation.map((item) => {
          const isActive = location === item.href;
          return (
            <Link key={item.name} href={item.href}>
              <div
                className={`flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all duration-200 cursor-pointer ${isActive
                    ? "bg-primary text-white shadow-lg shadow-primary/25"
                    : "text-slate-600 hover:bg-white hover:text-slate-900 hover:shadow-sm"
                  }`}
                onClick={() => setIsOpen(false)}
              >
                <item.icon className={`w-5 h-5 ${isActive ? "text-white" : "text-slate-400"}`} />
                {item.name}
              </div>
            </Link>
          );
        })}
      </nav>

      <div className="p-4 border-t border-slate-200 bg-white">
        <div className="flex items-center gap-3 px-2 mb-4">
          <div className="w-10 h-10 rounded-full bg-slate-100 flex items-center justify-center border border-slate-200">
            <UserCircle className="w-6 h-6 text-slate-400" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-slate-900 truncate">
              {user?.firstName} {user?.lastName}
            </p>
            <p className="text-xs text-muted-foreground capitalize">{user?.role}</p>
          </div>
        </div>
        <Button
          variant="outline"
          className="w-full justify-start gap-2 text-slate-600 hover:text-destructive hover:bg-destructive/5"
          onClick={() => logoutMutation.mutate()}
        >
          <LogOut className="w-4 h-4" />
          Sign Out
        </Button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-slate-50 flex">
      {/* Desktop Sidebar */}
      <div className="hidden md:block w-72 h-screen sticky top-0">
        <NavContent />
      </div>

      {/* Mobile Sidebar */}
      <div className="md:hidden fixed top-0 left-0 right-0 z-50 bg-white border-b px-4 py-3 flex items-center justify-between shadow-sm">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center text-white">
            <Video className="w-5 h-5" />
          </div>
          <span className="font-bold text-lg font-display text-slate-900">Ai-Listo</span>
        </div>
        <Sheet open={isOpen} onOpenChange={setIsOpen}>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon">
              <Menu className="w-6 h-6" />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="p-0 w-72">
            <NavContent />
          </SheetContent>
        </Sheet>
      </div>

      {/* Main Content */}
      <main className="flex-1 p-4 md:p-8 mt-16 md:mt-0 overflow-x-hidden">
        <div className="max-w-6xl mx-auto animate-in">
          {children}
        </div>
      </main>
    </div>
  );
}
