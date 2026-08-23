import React from "react";
import { Toaster } from "@/components/ui/toaster";
import {
  QueryClientProvider,
} from "@tanstack/react-query";
import {
  queryClientInstance,
} from "@/lib/query-client";
import {
  BrowserRouter as Router,
  Navigate,
  Route,
  Routes,
} from "react-router-dom";

import PageNotFound from "./lib/PageNotFound";
import {
  AuthProvider,
  useAuth,
} from "@/lib/AuthContext";
import ScrollToTop from "./components/ScrollToTop";

import Layout from "@/components/Layout";

import Dashboard from "@/pages/Dashboard";
import ResumeUpload from "@/pages/ResumeUpload";
import JobDiscovery from "@/pages/JobDiscovery";
import SettingsPage from "@/pages/Settings";
import Upskill from "@/pages/Upskill";
import ContextLibrary from "@/pages/ContextLibrary";
import InterviewPrep from "@/pages/InterviewPrep";

import Login from "@/pages/Login";
import Register from "@/pages/Register";
import ForgotPassword from "@/pages/ForgotPassword";
import ResetPassword from "@/pages/ResetPassword";

function AuthenticatedApp() {
  const {
    isLoadingAuth,
    isLoadingPublicSettings,
    isAuthenticated,
  } = useAuth();

  if (
    isLoadingPublicSettings ||
    isLoadingAuth
  ) {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-white/80 backdrop-blur-sm">
        <div className="w-8 h-8 border-4 border-slate-200 border-t-slate-800 rounded-full animate-spin" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <Navigate
        to="/login"
        replace
      />
    );
  }

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route
          path="/"
          element={<Dashboard />}
        />

        <Route
          path="/resume"
          element={<ResumeUpload />}
        />

        <Route
          path="/jobs"
          element={<JobDiscovery />}
        />

        <Route
          path="/upskill"
          element={<Upskill />}
        />

        <Route
          path="/context"
          element={<ContextLibrary />}
        />

        <Route
          path="/interview/:jobId"
          element={<InterviewPrep />}
        />

        <Route
          path="/settings"
          element={<SettingsPage />}
        />
      </Route>

      <Route
        path="*"
        element={<PageNotFound />}
      />
    </Routes>
  );
}

function PublicApp() {
  return (
    <Routes>
      <Route
        path="/login"
        element={<Login />}
      />

      <Route
        path="/register"
        element={<Register />}
      />

      <Route
        path="/forgot-password"
        element={<ForgotPassword />}
      />

      <Route
        path="/reset-password"
        element={<ResetPassword />}
      />

      <Route
        path="*"
        element={<AuthenticatedApp />}
      />
    </Routes>
  );
}

function App() {
  return (
    <AuthProvider>
      <QueryClientProvider
        client={queryClientInstance}
      >
        <Router>
          <ScrollToTop />
          <PublicApp />
        </Router>

        <Toaster />
      </QueryClientProvider>
    </AuthProvider>
  );
}

export default App;