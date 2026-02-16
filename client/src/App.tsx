import { Switch, Route, Redirect } from "wouter";
import { queryClient } from "./lib/queryClient";
import { QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useAuth } from "@/hooks/use-auth";
import { Loader2 } from "lucide-react";

import NotFound from "@/pages/not-found";
import LoginPage from "@/pages/auth-login";
import RegisterPage from "@/pages/auth-register";
import Dashboard from "@/pages/dashboard";
import LiveSession from "@/pages/live-session";
import ClassesPage from "@/pages/classes";

// Protected Route Wrapper
function ProtectedRoute({ component: Component }: { component: React.ComponentType }) {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-slate-50">
        <Loader2 className="w-10 h-10 animate-spin text-primary" />
      </div>
    );
  }

  if (!user) {
    return <Redirect to="/login" />;
  }

  return <Component />;
}

function Router() {
  return (
    <Switch>
      <Route path="/login" component={LoginPage} />
      <Route path="/register" component={RegisterPage} />
      
      {/* Protected Routes */}
      <Route path="/">
        <ProtectedRoute component={Dashboard} />
      </Route>
      <Route path="/live">
        <ProtectedRoute component={LiveSession} />
      </Route>
      <Route path="/classes">
        <ProtectedRoute component={ClassesPage} />
      </Route>
      
      {/* Placeholders for routes without explicit page implementation yet to prevent 404s during demo */}
      <Route path="/history">
        <ProtectedRoute component={() => (
          <div className="p-8"><h1 className="text-2xl font-bold">History Page (Coming Soon)</h1></div>
        )} />
      </Route>
      <Route path="/reports">
        <ProtectedRoute component={() => (
           <div className="p-8"><h1 className="text-2xl font-bold">Reports Page (Coming Soon)</h1></div>
        )} />
      </Route>

      <Route component={NotFound} />
    </Switch>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <Toaster />
        <Router />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

export default App;
