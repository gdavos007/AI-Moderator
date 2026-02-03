import { useEffect, useState } from "react";
import {
  RoomAudioRenderer,
  StartAudio,
  useRoomContext,
  useParticipants,
  useConnectionState,
} from "@livekit/components-react";
import { ConnectionState } from "livekit-client";
import type { GuideItem, SessionStatus, Role } from "../types";
import { getSessionStatus, SessionNotFoundError } from "../lib/session";
import TopBar from "./TopBar";
import TilesView from "./TilesView";
import SidePanel from "./SidePanel";
import BottomBar from "./BottomBar";

type ZoomShellProps = {
  sessionId: string;
  roomName: string;
  sessionStatus: SessionStatus;
  setSessionStatus: (status: SessionStatus) => void;
  role: Role;
  guideTitle: string;
  guideItems: GuideItem[];
  guideIndex: number;
  setGuideIndex: (fn: (n: number) => number) => void;
  onStartSession: () => Promise<void>;
  onEndSession: () => Promise<void>;
  onLeave: () => void;
  onSessionNotFound: () => void;
};

const ZoomShell = ({
  sessionId,
  roomName,
  sessionStatus,
  setSessionStatus,
  role,
  guideTitle,
  guideItems,
  guideIndex,
  setGuideIndex,
  onStartSession,
  onEndSession,
  onLeave,
  onSessionNotFound,
}: ZoomShellProps) => {
  const room = useRoomContext();
  const connectionState = useConnectionState();
  const participants = useParticipants();
  const [agentJoined, setAgentJoined] = useState(false);
  const [agentIdentity, setAgentIdentity] = useState<string | null>(null);
  const [mobileTab, setMobileTab] = useState<"tiles" | "roster" | "guide">("tiles");

  // STRUCTURED LOG: When connected to room
  useEffect(() => {
    if (connectionState === ConnectionState.Connected && room) {
      console.log(`[ui][ROOM_CONNECTED] roomName=${room.name} localParticipant=${room.localParticipant?.identity}`);
    }
  }, [connectionState, room]);

  // Poll session status every 2 seconds
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
        // Handle 404 - session no longer exists
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

  const onNextGuideItem = () => {
    setGuideIndex((current) => Math.min(current + 1, guideItems.length - 1));
  };

  const onPrevGuideItem = () => {
    setGuideIndex((current) => Math.max(current - 1, 0));
  };

  return (
    <div className="zoom-shell">
      {/* CRITICAL: Audio renderer for all participants including AI agent */}
      <RoomAudioRenderer />
      <StartAudio label="Click to enable audio" />

      {/* Top Bar */}
      <div className="zoom-topbar">
        <TopBar
          guideTitle={guideTitle}
          sessionStatus={sessionStatus}
          connectionState={connectionState}
          agentConnected={agentJoined}
          participantCount={participants.length}
          role={role}
          sessionId={sessionId}
          onStartSession={onStartSession}
          onEndSession={onEndSession}
        />
      </div>

      {/* Banners */}
      {sessionStatus === "waiting" && (
        <div style={{ padding: "0 12px" }}>
          <div className="banner">
            ⏳ Waiting for organizer to start the session. The AI moderator will join once started.
          </div>
        </div>
      )}
      {sessionStatus === "in_session" && agentJoined && (
        <div style={{ padding: "0 12px" }}>
          <div className="banner success">
            🎙️ Session is live! The AI moderator ({agentIdentity}) is connected. Make sure your speakers are on.
          </div>
        </div>
      )}
      {sessionStatus === "in_session" && !agentJoined && (
        <div style={{ padding: "0 12px" }}>
          <div className="banner warning">
            ⏳ Session started but waiting for AI moderator to join... This may take a few seconds.
          </div>
        </div>
      )}
      {sessionStatus === "ended" && (
        <div style={{ padding: "0 12px" }}>
          <div className="banner" style={{ background: "rgba(100, 100, 100, 0.3)", borderColor: "rgba(150, 150, 150, 0.4)" }}>
            ✅ Session has ended. Thank you for participating!
          </div>
        </div>
      )}

      {/* Mobile Tabs */}
      <div className="mobile-tabs-wrapper">
        <div className="tabs" style={{ margin: "8px 12px" }}>
          <div
            className={`tab ${mobileTab === "tiles" ? "tab--active" : ""}`}
            onClick={() => setMobileTab("tiles")}
          >
            Tiles
          </div>
          <div
            className={`tab ${mobileTab === "roster" ? "tab--active" : ""}`}
            onClick={() => setMobileTab("roster")}
          >
            Roster ({participants.length})
          </div>
          {role === "organizer" && (
            <div
              className={`tab ${mobileTab === "guide" ? "tab--active" : ""}`}
              onClick={() => setMobileTab("guide")}
            >
              Guide
            </div>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="zoom-body">
        <main className={`zoom-stage ${mobileTab !== "tiles" ? "hidden-mobile" : ""}`}>
          <TilesView agentIdentityHint={agentIdentity ?? undefined} />
        </main>

        <aside className="zoom-side">
          <SidePanel
            role={role}
            sessionStatus={sessionStatus}
            guideItems={guideItems}
            guideIndex={guideIndex}
            onPrevGuide={onPrevGuideItem}
            onNextGuide={onNextGuideItem}
            agentIdentityHint={agentIdentity ?? undefined}
          />
        </aside>

        {/* Mobile-only panels */}
        <div className={`mobile-panel ${mobileTab !== "roster" ? "hidden" : ""}`}>
          <div className="panel-card" style={{ margin: "0 12px" }}>
            <div className="panel-card__header">
              <span className="panel-card__title">Participants</span>
            </div>
            <SidePanel
              role={role}
              sessionStatus={sessionStatus}
              guideItems={guideItems}
              guideIndex={guideIndex}
              onPrevGuide={onPrevGuideItem}
              onNextGuide={onNextGuideItem}
              agentIdentityHint={agentIdentity ?? undefined}
            />
          </div>
        </div>
      </div>

      {/* Bottom Bar */}
      <div className="zoom-bottombar">
        <BottomBar
          role={role}
          sessionStatus={sessionStatus}
          onEndSession={onEndSession}
          onLeave={onLeave}
        />
      </div>

      {/* Debug Panel (dev mode only) */}
      {import.meta.env.DEV && (
        <div
          style={{
            position: "fixed",
            bottom: "calc(var(--bottombar-h) + 8px)",
            left: "12px",
            fontSize: "11px",
            color: "var(--muted-2)",
            zIndex: 50,
            background: "rgba(0, 0, 0, 0.7)",
            padding: "8px 12px",
            borderRadius: "6px",
            fontFamily: "monospace",
            lineHeight: "1.6",
            maxWidth: "400px",
          }}
        >
          <div style={{ fontWeight: "bold", marginBottom: "4px", color: "#888" }}>
            🐛 Debug Panel
          </div>
          <div>sessionId: <span style={{ color: "#4fc3f7" }}>{sessionId || "—"}</span></div>
          <div>roomName: <span style={{ color: "#4fc3f7" }}>{room?.name || "connecting..."}</span></div>
          <div>identity: <span style={{ color: "#4fc3f7" }}>{room?.localParticipant?.identity || "—"}</span></div>
          <div>role: <span style={{ color: "#4fc3f7" }}>{role}</span></div>
          <div>status: <span style={{ color: "#4fc3f7" }}>{sessionStatus}</span></div>
          <div>apiBaseUrl: <span style={{ color: "#4fc3f7", fontSize: "10px" }}>{import.meta.env.VITE_API_URL || "http://localhost:8000"}</span></div>
          <div>participants: <span style={{ color: "#4fc3f7" }}>{participants.length}</span></div>
          <div>agent: <span style={{ color: agentJoined ? "#81c784" : "#ffb74d" }}>{agentJoined ? `✓ ${agentIdentity}` : "waiting..."}</span></div>
        </div>
      )}
    </div>
  );
};

export default ZoomShell;
