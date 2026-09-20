import { useEffect } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { Shell } from "./components/Shell";
import { DetailSkeleton } from "./components/feedback";
import { setProjectId, setUnauthenticatedHandler } from "./lib/api";
import { keys, useMe, useProject, useProjects } from "./lib/queries";
import LoginPage from "./features/auth/LoginPage";
import NewProjectPage from "./features/onboarding/NewProjectPage";
import OnboardingPage from "./features/onboarding/OnboardingPage";
import InboxPage from "./features/inbox/InboxPage";
import AgentPage from "./features/agents/AgentPage";
import ContextPage from "./features/context/ContextPage";
import StatsPage from "./features/stats/StatsPage";
import SettingsPage from "./features/settings/SettingsPage";
import "./styles/shell.css";

export default function App() {
  const me = useMe();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();

  // A 403 on any call means the session went away; drop the cached user so the
  // router falls through to the login screen.
  useEffect(() => {
    setUnauthenticatedHandler(() => {
      queryClient.setQueryData(keys.me, null);
    });
    return () => setUnauthenticatedHandler(null);
  }, [queryClient]);

  const signedIn = !!me.data;
  const projects = useProjects(signedIn);
  const project = useProject(signedIn);

  // Keep the X-Project-Id header in step with what the server says is selected, so a
  // reload resumes on the same project rather than the first one.
  useEffect(() => {
    const current = projects.data?.find((p) => p.is_current) ?? projects.data?.[0];
    setProjectId(current?.id ?? null);
  }, [projects.data]);

  // Two gates, in order: an account with no project at all, then a project that hasn't
  // been onboarded. Both are states the user has to leave before the app is usable.
  const hasNoProject = signedIn && projects.isSuccess && projects.data.length === 0;
  const needsOnboarding =
    signedIn && !hasNoProject && project.isSuccess && !project.data.onboarded_at;

  useEffect(() => {
    if (hasNoProject && location.pathname !== "/projects/new") {
      navigate("/projects/new", { replace: true });
    } else if (
      needsOnboarding &&
      location.pathname !== "/onboarding" &&
      location.pathname !== "/projects/new"
    ) {
      navigate("/onboarding", { replace: true });
    }
  }, [hasNoProject, needsOnboarding, location.pathname, navigate]);

  if (me.isLoading) {
    return <DetailSkeleton />;
  }

  if (!signedIn) {
    return <LoginPage />;
  }

  return (
    <Routes>
      <Route path="/projects/new" element={<NewProjectPage first={hasNoProject} />} />
      <Route path="/onboarding" element={<OnboardingPage />} />
      <Route element={<Shell />}>
        <Route path="/inbox" element={<InboxPage />} />
        <Route path="/inbox/:draftId" element={<InboxPage />} />
        <Route path="/agents/:agentType" element={<AgentPage />} />
        <Route path="/context" element={<ContextPage />} />
        <Route path="/stats" element={<StatsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/inbox" replace />} />
    </Routes>
  );
}
