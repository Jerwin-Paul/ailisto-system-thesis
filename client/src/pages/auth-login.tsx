import { useState } from "react";
import { Link, useLocation } from "wouter";
import { useAuth } from "@/hooks/use-auth";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Eye, EyeOff, Loader2, Video } from "lucide-react";

const loginSchema = z.object({
  username: z.string().min(1, "Username is required"),
  password: z.string().min(1, "Password is required"),
});

export default function LoginPage() {
  const { loginMutation, user } = useAuth();
  const [showPassword, setShowPassword] = useState(false);
  const [, setLocation] = useLocation();

  // Redirect if already logged in
  if (user) {
    setLocation("/");
    return null;
  }

  const form = useForm<z.infer<typeof loginSchema>>({
    resolver: zodResolver(loginSchema),
    defaultValues: {
      username: "",
      password: "",
    },
  });

  function onSubmit(values: z.infer<typeof loginSchema>) {
    loginMutation.mutate(values);
  }

  return (
    <div className="min-h-screen grid lg:grid-cols-2">
      {/* Left: Branding */}
      <div className="hidden lg:flex flex-col justify-between bg-primary p-12 text-primary-foreground relative overflow-hidden">
        <div className="absolute inset-0 bg-blue-600 opacity-20 bg-[url('https://www.transparenttextures.com/patterns/cubes.png')]"></div>
        <div className="relative z-10">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-white/20 backdrop-blur-md flex items-center justify-center">
              <Video className="w-6 h-6 text-white" />
            </div>
            <span className="text-2xl font-bold font-display">Ai-Listo</span>
          </div>
        </div>
        
        <div className="relative z-10 max-w-lg">
          <h1 className="text-5xl font-bold font-display mb-6 leading-tight">
            Monitor Student Attention in Real-Time
          </h1>
          <p className="text-xl text-blue-100 leading-relaxed">
            Enhance classroom engagement with AI-powered insights. Designed for SSS Vilage Elementary School to support better learning outcomes.
          </p>
        </div>

        <div className="relative z-10 text-sm text-blue-200">
          © {new Date().getFullYear()} SSS Vilage Elementary School. All rights reserved.
        </div>
      </div>

      {/* Right: Login Form */}
      <div className="flex items-center justify-center p-8 bg-slate-50">
        <div className="w-full max-w-md space-y-8 bg-white p-8 rounded-3xl shadow-xl border border-slate-100">
          <div className="text-center">
            <h2 className="text-3xl font-bold font-display text-slate-900">Welcome Back</h2>
            <p className="mt-2 text-slate-500">Sign in to access your teacher dashboard</p>
          </div>

          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
              <FormField
                control={form.control}
                name="username"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Username</FormLabel>
                    <FormControl>
                      <Input 
                        placeholder="Enter your username" 
                        className="h-12 rounded-xl bg-slate-50 border-slate-200 focus:bg-white transition-all"
                        {...field} 
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="password"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Password</FormLabel>
                    <FormControl>
                      <div className="relative">
                        <Input
                          type={showPassword ? "text" : "password"}
                          placeholder="Enter your password"
                          className="h-12 rounded-xl bg-slate-50 border-slate-200 focus:bg-white transition-all pr-10"
                          {...field}
                        />
                        <button
                          type="button"
                          onClick={() => setShowPassword(!showPassword)}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                        >
                          {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
                        </button>
                      </div>
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="flex items-center justify-end">
                <Link href="/forgot-password">
                  <span className="text-sm font-medium text-primary hover:text-primary/80 cursor-pointer">
                    Forgot password?
                  </span>
                </Link>
              </div>

              <Button 
                type="submit" 
                disabled={loginMutation.isPending}
                className="w-full h-12 rounded-xl text-lg font-semibold shadow-lg shadow-primary/25 hover:shadow-xl hover:shadow-primary/30 transition-all"
              >
                {loginMutation.isPending ? (
                  <>
                    <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                    Signing in...
                  </>
                ) : (
                  "Sign In"
                )}
              </Button>
            </form>
          </Form>

          <div className="text-center pt-4 border-t border-slate-100">
            <p className="text-sm text-slate-500">
              Don't have an account?{" "}
              <Link href="/register">
                <span className="font-semibold text-primary hover:text-primary/80 cursor-pointer">
                  Create an account
                </span>
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
