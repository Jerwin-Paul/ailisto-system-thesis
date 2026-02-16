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

const registerSchema = z.object({
  firstName: z.string().min(1, "First name is required"),
  lastName: z.string().min(1, "Last name is required"),
  username: z.string().min(3, "Username must be at least 3 characters"),
  password: z.string().min(6, "Password must be at least 6 characters"),
  confirmPassword: z.string().min(6, "Confirm password is required"),
}).refine((data) => data.password === data.confirmPassword, {
  message: "Passwords do not match",
  path: ["confirmPassword"],
});

export default function RegisterPage() {
  const { registerMutation, user } = useAuth();
  const [showPassword, setShowPassword] = useState(false);
  const [, setLocation] = useLocation();

  if (user) {
    setLocation("/");
    return null;
  }

  const form = useForm<z.infer<typeof registerSchema>>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      firstName: "",
      lastName: "",
      username: "",
      password: "",
      confirmPassword: "",
    },
  });

  function onSubmit(values: z.infer<typeof registerSchema>) {
    const { confirmPassword, ...data } = values;
    registerMutation.mutate(data, {
      onSuccess: () => setLocation("/login"),
    });
  }

  return (
    <div className="min-h-screen flex flex-col justify-center items-center p-6 bg-slate-50">
      <div className="mb-8 text-center">
        <div className="w-16 h-16 bg-primary rounded-2xl mx-auto flex items-center justify-center text-white shadow-xl shadow-primary/25 mb-4">
          <Video className="w-8 h-8" />
        </div>
        <h1 className="text-3xl font-bold font-display text-slate-900">Create Account</h1>
        <p className="text-slate-500 mt-2">Join SSS Vilage Elementary School's monitoring system</p>
      </div>

      <div className="w-full max-w-lg bg-white p-8 rounded-3xl shadow-xl border border-slate-100">
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <FormField
                control={form.control}
                name="firstName"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>First Name</FormLabel>
                    <FormControl>
                      <Input className="h-11 rounded-xl" placeholder="John" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="lastName"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Last Name</FormLabel>
                    <FormControl>
                      <Input className="h-11 rounded-xl" placeholder="Doe" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <FormField
              control={form.control}
              name="username"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Username</FormLabel>
                  <FormControl>
                    <Input className="h-11 rounded-xl" placeholder="johndoe123" {...field} />
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
                        className="h-11 rounded-xl pr-10"
                        placeholder="••••••"
                        {...field}
                      />
                      <button
                        type="button"
                        onClick={() => setShowPassword(!showPassword)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400"
                      >
                        {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                      </button>
                    </div>
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="confirmPassword"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Confirm Password</FormLabel>
                  <FormControl>
                    <Input
                      type={showPassword ? "text" : "password"}
                      className="h-11 rounded-xl"
                      placeholder="••••••"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <Button
              type="submit"
              disabled={registerMutation.isPending}
              className="w-full h-12 rounded-xl text-base font-semibold mt-2"
            >
              {registerMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                  Creating Account...
                </>
              ) : (
                "Create Account"
              )}
            </Button>
          </form>
        </Form>

        <div className="text-center pt-6 mt-4 border-t border-slate-100">
          <p className="text-sm text-slate-500">
            Already have an account?{" "}
            <Link href="/login">
              <span className="font-semibold text-primary hover:text-primary/80 cursor-pointer">
                Sign In
              </span>
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
