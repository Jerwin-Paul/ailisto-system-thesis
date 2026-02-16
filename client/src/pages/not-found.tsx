import { Link } from "wouter";
import { Button } from "@/components/ui/button";
import { AlertTriangle } from "lucide-react";

export default function NotFound() {
  return (
    <div className="min-h-screen w-full flex flex-col items-center justify-center bg-slate-50 p-4">
      <div className="w-24 h-24 bg-amber-100 rounded-full flex items-center justify-center mb-6">
        <AlertTriangle className="w-12 h-12 text-amber-500" />
      </div>
      <h1 className="text-4xl font-bold font-display text-slate-900 mb-2">Page Not Found</h1>
      <p className="text-slate-500 mb-8 max-w-md text-center">
        Oops! The page you are looking for doesn't exist or has been moved.
      </p>
      <Link href="/">
        <Button className="h-12 px-8 rounded-xl text-lg font-semibold">
          Return Home
        </Button>
      </Link>
    </div>
  );
}
