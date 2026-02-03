import { useState } from "react";
import { ConnectionState } from "livekit-client";
import type { SessionStatus, Role } from "../types";

const statusLabels: Record<SessionStatus, string> = {
  waiting: "Waiting to start",
  in_session: "In session",
  ended: "Ended",
};

type TopBarProps = {
  guideTitle: string;
  sessionStatus: SessionStatus;
  connectionState: ConnectionState;
  agentConnected: boolean;
  participantCount: number;
  role: Role;
  sessionId: string;
  onStartSession: () => void;
  onEndSession: () => void;
};

const TopBar = ({
  guideTitle,
  sessionStatus,
  connectionState,
  agentConnected,
  participantCount,
  role,
  sessionId,
  onStartSession,
  onEndSession,
}: TopBarProps) => {
  const isConnected = connectionState === ConnectionState.Connected;
  const [copied, setCopied] = useState(false);
  
  // Generate shareable link
  const getShareLink = () => {
    const url = new URL(window.location.href);
    url.searchParams.set("session", sessionId);
    return url.toString();
  };
  
  const handleCopyLink = async () => {
    try {
      await navigator.clipboard.writeText(getShareLink());
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy link:", err);
    }
  };

  return (
    <>
      <div className="zoom-topbar__left">
        <span className="zoom-title">
          {guideTitle}
          <span className="zoom-title__badge">{participantCount} participants</span>
        </span>
      </div>

      <div className="zoom-topbar__center">
        <span className={`pill ${sessionStatus === "in_session" ? "pill--live" : ""}`}>
          <span className={`dot ${sessionStatus === "in_session" ? "dot--bad" : "dot--warn"}`} />
          {statusLabels[sessionStatus]}
        </span>
        <span className="pill">
          <span className={`dot ${isConnected ? "dot--ok" : "dot--warn"}`} />
          {isConnected ? "Connected" : "Connecting..."}
        </span>
        <span className="pill">
          <span className={`dot ${agentConnected ? "dot--ok" : "dot--warn"}`} />
          AI {agentConnected ? "Ready" : "Waiting..."}
        </span>
      </div>

      <div className="zoom-topbar__right">
        {/* Share Link button - always visible for organizer when session exists */}
        {role === "organizer" && sessionId && (
          <button 
            className="btn btn--secondary" 
            type="button" 
            onClick={handleCopyLink}
            style={{ marginRight: "8px" }}
            title={getShareLink()}
          >
            {copied ? "✓ Copied!" : "📋 Share Link"}
          </button>
        )}
        {role === "organizer" && sessionStatus === "waiting" && (
          <button className="btn btn--primary" type="button" onClick={onStartSession}>
            Start session
          </button>
        )}
        {role === "organizer" && sessionStatus === "in_session" && (
          <button className="btn btn--danger" type="button" onClick={onEndSession}>
            End session
          </button>
        )}
      </div>
    </>
  );
};

export default TopBar;
