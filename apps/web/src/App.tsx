import { useEffect, useMemo, useState, useCallback } from "react";
import {
  LiveKitRoom,
  RoomAudioRenderer,
  StartAudio,
  useRoomContext,
  useParticipants,
  useConnectionState,
  useTracks,
  TrackLoop,
  ParticipantTile,
  GridLayout,
  ControlBar,
} from "@livekit/components-react";
import "@livekit/components-styles";
import { Track, ConnectionState } from "livekit-client";
import "./styles.css";
import type { GuideItem, SessionStatus, Role } from "./types";
import { getGuideItems, getGuideMeta } from "./lib/guide";
import { createSession, joinSession, startSession, endSession, getSession, getSessionStatus, SessionNotFoundError } from "./lib/session";

const UI_NOTICE = "This session may be recorded/transcribed.";
const LIVEKIT_URL = import.meta.env.VITE_LIVEKIT_URL ?? "wss://ai-XXXXXXXXXXX.livekit.cloud";

const statusLabels: Record<SessionStatus, string> = {
  waiting: "Waiting to start",
  in_session: "In session",
  ended: "Ended"
};

const joinNotice = {
  version: "v1",
  text: UI_NOTICE
};

const getGuideTitle = () => {
  const meta = getGuideMeta();
  return meta.title;
};

const getGuideItemsForSession = (): GuideItem[] => getGuideItems();

// LiveKit Room Content Component
const RoomContent = ({
  sessionId,
  sessionStatus,
  setSessionStatus,
  role,
  displayName,
  guideItems,
  guideIndex,
  setGuideIndex,
  apiAvailable,
  setApiAvailable,
  onSessionNotFound,
  roomName,
}: {
  sessionId: string;
  sessionStatus: SessionStatus;
  setSessionStatus: (status: SessionStatus) => void;
  role: Role;
  displayName: string;
  guideItems: GuideItem[];
  guideIndex: number;
  setGuideIndex: (fn: (n: number) => number) => void;
  apiAvailable: boolean;
  setApiAvailable: (v: boolean) => void;
  onSessionNotFound: () => void;
  roomName: string;
}) => {
  const room = useRoomContext();
  const connectionState = useConnectionState();
  const participants = useParticipants();
  const tracks = useTracks(
    [
      { source: Track.Source.Camera, withPlaceholder: true },
      { source: Track.Source.ScreenShare, withPlaceholder: false },
    ],
    { onlySubscribed: false }
  );
  const audioTracks = useTracks([Track.Source.Microphone]);
  const [mobileTab, setMobileTab] = useState<"tiles" | "roster" | "moderator">("tiles");
  const [agentJoined, setAgentJoined] = useState(false);
  const [agentIdentity, setAgentIdentity] = useState<string | null>(null);
  
  const guideTitle = getGuideTitle();
  const currentGuideItem = guideItems[guideIndex];

  // STRUCTURED LOG: When connected to room
  useEffect(() => {
    if (connectionState === ConnectionState.Connected && room) {
      console.log(`[ui][ROOM_CONNECTED] roomName=${room.name} localParticipant=${room.localParticipant?.identity}`);
    }
  }, [connectionState, room]);

  // Poll session status with agent presence check
  useEffect(() => {
    if (!sessionId) return;
    
    const interval = setInterval(async () => {
      try {
        const status = await getSessionStatus(sessionId);
        if (status.status !== sessionStatus) {
          setSessionStatus(status.status as SessionStatus);
        }
        // Update agent status
        if (status.agentJoined !== agentJoined) {
          setAgentJoined(status.agentJoined);
          if (status.agentJoined) {
            console.log(`[ui][AGENT_JOINED] roomName=${roomName} agentIdentity=${status.agentIdentity}`);
          }
        }
        if (status.agentIdentity) {
          setAgentIdentity(status.agentIdentity);
        }
      } catch (e) {
        // Handle 404 - session no longer exists (e.g., API restarted)
        if (e instanceof SessionNotFoundError) {
          console.warn("[ui][SESSION_NOT_FOUND] redirecting to join page:", sessionId);
          onSessionNotFound();
          return;
        }
        console.error("[ui][POLL_ERROR]", e);
      }
    }, 2000);
    
    return () => clearInterval(interval);
  }, [sessionId, sessionStatus, setSessionStatus, onSessionNotFound, agentJoined, roomName]);

  const onStartSession = async () => {
    if (!sessionId) return;
    try {
      await startSession(sessionId);
      setSessionStatus("in_session");
    } catch (e) {
      if (e instanceof SessionNotFoundError) {
        console.warn("Session not found when trying to start:", sessionId);
        onSessionNotFound();
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
        onSessionNotFound();
        return;
      }
      console.error("Failed to end session:", e);
      setApiAvailable(false);
    }
  };

  const onNextGuideItem = () => {
    setGuideIndex((current) => Math.min(current + 1, guideItems.length - 1));
  };

  const onPrevGuideItem = () => {
    setGuideIndex((current) => Math.max(current - 1, 0));
  };

  const isConnected = connectionState === ConnectionState.Connected;

  return (
    <div className="page session-page">
      <header className="top-bar">
        <div>
          <h2>{guideTitle}</h2>
          <p className="status">
            Session: <strong>{statusLabels[sessionStatus]}</strong>
            {" | "}
            Room: <strong>{isConnected ? "Connected ✅" : "Connecting..."}</strong>
            {" | "}
            AI Agent: <strong>{agentJoined ? "Joined ✅" : "Waiting..."}</strong>
            {" | "}
            Participants: <strong>{participants.length}</strong>
          </p>
        </div>
        <div className="status-actions">
          {role === "organizer" && sessionStatus === "waiting" && (
            <button className="primary" type="button" onClick={onStartSession}>
              Start session
            </button>
          )}
          {role === "organizer" && sessionStatus === "in_session" && (
            <button className="ghost" type="button" onClick={onEndSession}>
              End session
            </button>
          )}
        </div>
      </header>

      {sessionStatus === "waiting" && (
        <div className="banner">
          ⏳ Waiting for organizer to start the session. The AI moderator will join once started.
        </div>
      )}

      {sessionStatus === "in_session" && agentJoined && (
        <div className="banner success">
          🎙️ Session is live! The AI moderator ({agentIdentity}) is connected. Make sure your speakers are on.
        </div>
      )}

      {sessionStatus === "in_session" && !agentJoined && (
        <div className="banner warning">
          ⏳ Session started but waiting for AI moderator to join... This may take a few seconds.
        </div>
      )}

      {/* CRITICAL: This renders audio from all participants including the AI agent */}
      <RoomAudioRenderer />
      
      {/* StartAudio button for browsers that require user gesture to play audio */}
      <StartAudio label="Click to enable audio" />

      <div className="mobile-tabs">
        <button
          className={mobileTab === "tiles" ? "active" : ""}
          type="button"
          onClick={() => setMobileTab("tiles")}
        >
          Tiles
        </button>
        <button
          className={mobileTab === "roster" ? "active" : ""}
          type="button"
          onClick={() => setMobileTab("roster")}
        >
          Roster ({participants.length})
        </button>
        <button
          className={mobileTab === "moderator" ? "active" : ""}
          type="button"
          onClick={() => setMobileTab("moderator")}
        >
          Moderator
        </button>
      </div>

      <main className="layout">
        <section className={`tiles ${mobileTab !== "tiles" ? "hidden-mobile" : ""}`}>
          <h3>Room - {participants.length} participant(s)</h3>
          
          {/* LiveKit Grid Layout for video tiles */}
          <div className="lk-grid-layout-wrapper" style={{ height: "400px" }}>
            <GridLayout tracks={tracks}>
              <ParticipantTile />
            </GridLayout>
          </div>

          {/* Participant list */}
          <div className="participant-list">
            {participants.map((participant) => {
              const isLocal = participant.isLocal;
              const isSpeaking = participant.isSpeaking;
              const identity = participant.identity;
              const name = participant.name || identity;
              const isAgent = identity.toLowerCase().includes("agent") || 
                             name.toLowerCase().includes("moderator") ||
                             name.toLowerCase().includes("agent");
              
              return (
                <div
                  key={participant.sid}
                  className={`participant-card ${isSpeaking ? "speaking" : ""} ${isAgent ? "agent" : ""}`}
                >
                  <span className="participant-name">
                    {name} {isLocal && "(You)"} {isAgent && "🤖"}
                  </span>
                  <span className="participant-status">
                    {isSpeaking ? "🗣️ Speaking" : "🔇 Silent"}
                    {participant.isMicrophoneEnabled && " | 🎤 Mic On"}
                  </span>
                </div>
              );
            })}
            {participants.length === 0 && (
              <div className="participant-card">
                <span>Connecting to room...</span>
              </div>
            )}
          </div>
        </section>

        <aside className={`roster ${mobileTab !== "roster" ? "hidden-mobile" : ""}`}>
          <h3>Roster</h3>
          <p className="status">{statusLabels[sessionStatus]}</p>
          <ul>
            {participants.map((participant) => {
              const identity = participant.identity;
              const name = participant.name || identity;
              const isAgent = identity.toLowerCase().includes("agent");
              return (
                <li key={participant.sid}>
                  <div className="roster-row">
                    <span>{name} {isAgent && "🤖"}</span>
                    <span className="roster-meta">
                      {participant.isLocal ? "You" : "Connected"}
                    </span>
                  </div>
                  <div className="roster-row secondary">
                    <span>{participant.isSpeaking ? "🗣️ Speaking" : "Silent"}</span>
                  </div>
                </li>
              );
            })}
          </ul>
          {participants.length === 0 && (
            <p className="status">No participants yet</p>
          )}
        </aside>

        <section className={`moderator ${mobileTab !== "moderator" ? "hidden-mobile" : ""}`}>
          <h3>Moderator guide</h3>
          {sessionStatus === "waiting" && (
            <p className="status">{statusLabels[sessionStatus]}</p>
          )}
          {sessionStatus !== "waiting" && currentGuideItem && (
            <div className="guide-card">
              <div className="guide-meta">
                <span>{currentGuideItem.sectionTitle}</span>
                <span>
                  {guideIndex + 1} / {guideItems.length}
                </span>
              </div>
              <p className="guide-type">{currentGuideItem.type}</p>
              <p className="guide-text">{currentGuideItem.text}</p>
              {role === "organizer" && (
                <div className="guide-actions">
                  <button type="button" onClick={onPrevGuideItem}>
                    Previous
                  </button>
                  <button className="primary" type="button" onClick={onNextGuideItem}>
                    Next
                  </button>
                </div>
              )}
            </div>
          )}
        </section>
      </main>

      {/* LiveKit Control Bar */}
      <div className="control-bar-wrapper">
        <ControlBar variation="minimal" />
      </div>

      <footer className="footer">
        <div>
          <span>Room: {room?.name || "connecting..."}</span>
          <span>Session ID: {sessionId || "pending"}</span>
        </div>
        {!apiAvailable && (
          <span className="warning">
            API offline — some features may not work
          </span>
        )}
      </footer>
    </div>
  );
};

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
  const [agentJoined, setAgentJoined] = useState(false);
  const [livekitUrl, setLivekitUrl] = useState(LIVEKIT_URL);

  const guideItems = useMemo(getGuideItemsForSession, []);

  // Reset to join page (e.g., when session 404s)
  const resetToJoinPage = useCallback(() => {
    setStep("join");
    setSessionId("");
    setRoomName("");
    setToken("");
    setSessionStatus("waiting");
    setGuideIndex(0);
    setError("Session expired or not found. Please create a new session.");
  }, []);

  const onJoin = async () => {
    if (!displayName.trim()) {
      setError("Display name is required");
      return;
    }
    
    setIsJoining(true);
    setError("");

    try {
      // First create a session
      const session = await createSession("focus-group");
      
      // STRUCTURED LOG: Session created
      console.log(`[ui][SESSION_CREATE] sessionId=${session.id} roomName=${session.roomName}`);
      
      setSessionId(session.id);
      setRoomName(session.roomName);
      setSessionStatus(session.status);
      
      // Then join and get token
      const joinResponse = await joinSession(
        session.id,
        displayName.trim(),
        email.trim() || undefined,
        role === "organizer"
      );
      
      // STRUCTURED LOG: Joined session, about to connect
      console.log(`[ui][JOIN_SUCCESS] sessionId=${session.id} roomName=${joinResponse.roomName} identity=${joinResponse.identity}`);
      
      // Use LiveKit URL from API response if available
      if (joinResponse.livekitUrl) {
        setLivekitUrl(joinResponse.livekitUrl);
      }
      
      setToken(joinResponse.token);
      setStep("session");
    } catch (e) {
      console.error("[ui][JOIN_ERROR]", e);
      setError("Failed to connect. Make sure the API server is running (make dev-api)");
      setApiAvailable(false);
    } finally {
      setIsJoining(false);
    }
  };

  if (step === "join") {
    return (
      <div className="page join-page">
        <div className="card join-card">
          <h1>Join Focus Group</h1>
          <p className="notice">{joinNotice.text}</p>
          
          {error && (
            <div className="error-banner">
              {error}
            </div>
          )}
          
          <label>
            Display name (required)
            <input
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder="Your name"
              required
            />
          </label>
          <label>
            Email (optional)
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
            />
          </label>
          <div className="role-toggle">
            <span>Role</span>
            <button
              className={role === "participant" ? "active" : ""}
              type="button"
              onClick={() => setRole("participant")}
            >
              Participant
            </button>
            <button
              className={role === "organizer" ? "active" : ""}
              type="button"
              onClick={() => setRole("organizer")}
            >
              Organizer
            </button>
          </div>
          <button 
            className="primary" 
            type="button" 
            onClick={onJoin}
            disabled={isJoining}
          >
            {isJoining ? "Connecting..." : "Join session"}
          </button>
          
          <p className="help-text">
            Make sure you have these services running:<br/>
            <code>make dev-api</code> (API server)<br/>
            <code>make dev-agent</code> (AI Moderator)
          </p>
        </div>
      </div>
    );
  }

  // Connected to LiveKit room using official LiveKitRoom component
  // Reference: https://docs.livekit.io/reference/components/react/component/livekitroom/
  return (
    <LiveKitRoom
      token={token}
      serverUrl={LIVEKIT_URL}
      connect={true}
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
      <RoomContent
        sessionId={sessionId}
        sessionStatus={sessionStatus}
        setSessionStatus={setSessionStatus}
        role={role}
        displayName={displayName}
        guideItems={guideItems}
        guideIndex={guideIndex}
        setGuideIndex={setGuideIndex}
        apiAvailable={apiAvailable}
        setApiAvailable={setApiAvailable}
        onSessionNotFound={resetToJoinPage}
        roomName={roomName}
      />
    </LiveKitRoom>
  );
};

export default App;
