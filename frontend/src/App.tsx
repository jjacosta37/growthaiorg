import { useEffect } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { Shell } from "./components/Shell";
import { DetailSkeleton } from "./components/feedback";
import { setProjectId, setUnauthenticatedHandler } from "./lib/api";
import { keys, useMe, useProject, useProjects } from "./lib/queries";
import LoginPage from "./features/auth/LoginPage";
import LandingPage from "./features/landing/LandingPage";
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
  // /api/project/ 409s when the user owns none, so don't ask until we know there is one.
  const hasAny = (projects.data?.length ?? 0) > 0;
  const project = useProject(signedIn && hasAny);

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

  // Naming a project and crawling its site are one screen, so both states land on
  // /onboarding: with no project it creates one, otherwise it onboards the current one.
  useEffect(() => {
    if ((hasNoProject || needsOnboarding) && location.pathname !== "/onboarding") {
      navigate("/onboarding", { replace: true });
    }
  }, [hasNoProject, needsOnboarding, location.pathname, navigate]);

  // Visitors to / see the landing page straight away rather than an app skeleton while
  // the session check is in flight; a signed-in user is sent on to the inbox once it lands.
  if (me.isLoading) {
    return location.pathname === "/" ? <LandingPage /> : <DetailSkeleton />;
  }

  // Signed out: / is the public landing page; every other path (including /login and
  // deep links into the app) shows the login screen.
  if (!signedIn) {
    return (
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="*" element={<LoginPage />} />
      </Routes>
    );
  }

  return (
    <Routes>
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
