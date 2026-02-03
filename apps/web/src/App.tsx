import { useEffect, useMemo, useState, useCallback } from "react";
import {
  LiveKitRoom,
  RoomAudioRenderer,
} from "@livekit/components-react";
import "@livekit/components-styles";
import "./styles.css";
import type { GuideItem, SessionStatus, Role } from "./types";
import { getGuideItems, getGuideMeta } from "./lib/guide";
import { createSession, joinSession, startSession, endSession, SessionNotFoundError } from "./lib/session";
import { JoinPage, ZoomShell } from "./components";

const LIVEKIT_URL = import.meta.env.VITE_LIVEKIT_URL ?? "wss://ai-moderator-pkxfi93j.livekit.cloud";
const API_BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

// Helper: Parse sessionId from URL query string
const getSessionIdFromUrl = (): string | null => {
  const params = new URLSearchParams(window.location.search);
  return params.get("session");
};

// Helper: Update URL with session parameter (without page reload)
const updateUrlWithSession = (sessionId: string) => {
  const url = new URL(window.location.href);
  url.searchParams.set("session", sessionId);
  window.history.replaceState({}, "", url.toString());
};

const getGuideTitle = () => {
  const meta = getGuideMeta();
  return meta.title;
};

const getGuideItemsForSession = (): GuideItem[] => getGuideItems();

const App = () => {
  const [step, setStep] = useState<"join" | "session">("join");
  const [role, setRole] = useState<Role>("organizer");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [roomName, setRoomName] = useState("");
  const [token, setToken] = useState("");
  const [sessionStatus, setSessionStatus] = useState<SessionStatus>("waiting");
  const [guideIndex, setGuideIndex] = useState(0);
  const [apiAvailable, setApiAvailable] = useState(true);
  const [isJoining, setIsJoining] = useState(false);
  const [error, setError] = useState("");
  const [livekitUrl, setLivekitUrl] = useState(LIVEKIT_URL);
  
  // URL-based session: parsed from ?session=xxx on mount
  const [urlSessionId, setUrlSessionId] = useState<string | null>(null);
  
  // Parse sessionId from URL on mount
  useEffect(() => {
    const sessionFromUrl = getSessionIdFromUrl();
    if (sessionFromUrl) {
      setUrlSessionId(sessionFromUrl);
      console.log(`[ui][URL_SESSION] Found sessionId in URL: ${sessionFromUrl}`);
    }
  }, []);

  const guideItems = useMemo(getGuideItemsForSession, []);
  const guideTitle = useMemo(getGuideTitle, []);

  // Reset to join page (e.g., when session 404s)
  const resetToJoinPage = useCallback(() => {
    setStep("join");
    setSessionId("");
    setRoomName("");
    setToken("");
    setSessionStatus("waiting");
    setGuideIndex(0);
    setUrlSessionId(null);
    // Clear session from URL
    const url = new URL(window.location.href);
    url.searchParams.delete("session");
    window.history.replaceState({}, "", url.toString());
    setError("Session expired or not found. Please create a new session.");
  }, []);

  const onJoin = async (data: { displayName: string; email: string; role: Role }) => {
    const { displayName: name, email: userEmail, role: userRole } = data;

    if (!name.trim()) {
      setError("Display name is required");
      return;
    }

    // CASE: Participant trying to join without a session URL
    // They must use a shared link from the organizer
    if (userRole === "participant" && !urlSessionId) {
      setError("Please ask the organizer for the session link to join.");
      return;
    }

    setIsJoining(true);
    setError("");
    setDisplayName(name);
    setEmail(userEmail);
    setRole(userRole);

    try {
      let targetSessionId = urlSessionId;

      // CASE: Organizer creating a new session (no session in URL)
      if (!urlSessionId && userRole === "organizer") {
        const session = await createSession("focus-group");
        
        // STRUCTURED LOG: Session created
        console.log(`[ui][SESSION_CREATE] sessionId=${session.id} roomName=${session.roomName}`);
        
        targetSessionId = session.id;
        setSessionId(session.id);
        setRoomName(session.roomName);
        setSessionStatus(session.status);
        
        // Update URL with session ID so organizer can share the link
        updateUrlWithSession(session.id);
        setUrlSessionId(session.id);
      }

      // CASE: Joining an existing session (from URL or just created)
      if (!targetSessionId) {
        throw new Error("No session to join");
      }

      const joinResponse = await joinSession(
        targetSessionId,
        name.trim(),
        userEmail.trim() || undefined,
        userRole === "organizer"
      );

      // STRUCTURED LOG: Joined session, about to connect
      console.log(`[ui][JOIN_SUCCESS] sessionId=${targetSessionId} roomName=${joinResponse.roomName} identity=${joinResponse.identity} apiBaseUrl=${API_BASE_URL}`);

      // Update state with session info from API
      setSessionId(targetSessionId);
      setRoomName(joinResponse.roomName);

      // Use LiveKit URL from API response if available
      if (joinResponse.livekitUrl) {
        setLivekitUrl(joinResponse.livekitUrl);
      }

      setToken(joinResponse.token);
      setStep("session");
    } catch (e) {
      console.error("[ui][JOIN_ERROR]", e);
      if (e instanceof SessionNotFoundError) {
        setError("Session not found. The link may be expired or invalid.");
      } else {
        setError("Failed to connect. Make sure the API server is running (make dev-api).");
      }
      setApiAvailable(false);
    } finally {
      setIsJoining(false);
    }
  };

  const onStartSession = async () => {
    if (!sessionId) return;
    try {
      await startSession(sessionId);
      setSessionStatus("in_session");
    } catch (e) {
      if (e instanceof SessionNotFoundError) {
        console.warn("Session not found when trying to start:", sessionId);
        resetToJoinPage();
        return;
      }
      console.error("Failed to start session:", e);
      setApiAvailable(false);
    }
  };

  const onEndSession = async () => {
    if (!sessionId) return;
    try {
      await endSession(sessionId);
      setSessionStatus("ended");
    } catch (e) {
      if (e instanceof SessionNotFoundError) {
        console.warn("Session not found when trying to end:", sessionId);
        resetToJoinPage();
        return;
      }
      console.error("Failed to end session:", e);
      setApiAvailable(false);
    }
  };

  // Join page
  if (step === "join") {
    return (
      <JoinPage 
        onJoin={onJoin} 
        error={error} 
        isJoining={isJoining} 
        urlSessionId={urlSessionId}
      />
    );
  }

  // Session page - wrapped in LiveKitRoom
  // Reference: https://docs.livekit.io/reference/components/react/component/livekitroom/
  // Disconnect when session ends to stop receiving audio from agent
  const shouldConnect = sessionStatus !== "ended";

  return (
    <LiveKitRoom
      token={token}
      serverUrl={livekitUrl}
      connect={shouldConnect}
      audio={true}
      video={false}
      onConnected={() => {
        console.log("✅ Connected to LiveKit room!");
      }}
      onDisconnected={(reason) => {
        console.log("❌ Disconnected from room:", reason);
      }}
      onError={(error) => {
        console.error("LiveKit error:", error);
      }}
    >
      <ZoomShell
        sessionId={sessionId}
        roomName={roomName}
        sessionStatus={sessionStatus}
        setSessionStatus={setSessionStatus}
        role={role}
        guideTitle={guideTitle}
        guideItems={guideItems}
        guideIndex={guideIndex}
        setGuideIndex={setGuideIndex}
        onStartSession={onStartSession}
        onEndSession={onEndSession}
        onLeave={resetToJoinPage}
        onSessionNotFound={resetToJoinPage}
      />
    </LiveKitRoom>
  );
};

export default App;
