import { useState, useEffect } from "react";
import type { Role } from "../types";

const ORGANIZER_PASSWORD = "ABC12345!";

const UI_NOTICE = "This session may be recorded/transcribed.";

type JoinPageProps = {
  onJoin: (data: { displayName: string; email: string; role: Role }) => void;
  error: string;
  isJoining: boolean;
  urlSessionId: string | null; // Session ID from URL (if joining via shared link)
};

const JoinPage = ({ onJoin, error, isJoining, urlSessionId }: JoinPageProps) => {
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  // Default to participant when joining via shared link, organizer when creating new session
  const [role, setRole] = useState<Role>(urlSessionId ? "participant" : "organizer");
  const [password, setPassword] = useState("");
  const [passwordError, setPasswordError] = useState("");
  
  // Update default role when urlSessionId changes
  useEffect(() => {
    if (urlSessionId) {
      setRole("participant");
    }
  }, [urlSessionId]);

  const handleJoin = () => {
    // Validate display name
    if (!displayName.trim()) {
      return;
    }

    // Validate organizer password (state only, never persisted)
    if (role === "organizer" && password !== ORGANIZER_PASSWORD) {
      setPasswordError("Invalid organizer password");
      return; // Block API call
    }

    setPasswordError("");
    onJoin({ displayName: displayName.trim(), email: email.trim(), role });
  };

  return (
    <div className="join-shell">
      <div className="join-card">
        <div className="join-card__header">
          <h1 className="join-title">Join Focus Group</h1>
          <p className="join-subtitle">{UI_NOTICE}</p>
        </div>

        <div className="join-card__body">
          {error && <div className="error-banner">{error}</div>}
          
          {/* Info banner when joining via shared link */}
          {urlSessionId && (
            <div className="info-banner" style={{ 
              background: "rgba(79, 124, 255, 0.15)", 
              border: "1px solid rgba(79, 124, 255, 0.3)",
              borderRadius: "8px",
              padding: "12px",
              marginBottom: "16px",
              fontSize: "14px"
            }}>
              📎 You're joining an existing session. Enter your name below.
            </div>
          )}
          
          {/* Warning for participant without shared link */}
          {!urlSessionId && role === "participant" && (
            <div className="warning-banner" style={{ 
              background: "rgba(255, 193, 7, 0.15)", 
              border: "1px solid rgba(255, 193, 7, 0.3)",
              borderRadius: "8px",
              padding: "12px",
              marginBottom: "16px",
              fontSize: "14px"
            }}>
              ⚠️ To join as a participant, you need a session link from the organizer.
              <br />
              <span style={{ fontSize: "12px", opacity: 0.8 }}>
                Switch to Organizer to create a new session.
              </span>
            </div>
          )}

          <div className="field">
            <label className="label" htmlFor="displayName">
              Display name (required)
            </label>
            <input
              id="displayName"
              className="input"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Your name"
              required
            />
          </div>

          <div className="field">
            <label className="label" htmlFor="email">
              Email (optional)
            </label>
            <input
              id="email"
              type="email"
              className="input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
            />
          </div>

          <div className="field">
            <span className="label">Role</span>
            <div className="join-role-toggle">
              <button
                type="button"
                className={`join-role-btn ${role === "participant" ? "join-role-btn--active" : ""}`}
                aria-pressed={role === "participant"}
                onClick={() => {
                  setRole("participant");
                  setPassword("");
                  setPasswordError("");
                }}
              >
                Participant
              </button>
              <button
                type="button"
                className={`join-role-btn ${role === "organizer" ? "join-role-btn--active" : ""}`}
                aria-pressed={role === "organizer"}
                onClick={() => setRole("organizer")}
              >
                Organizer
              </button>
            </div>
          </div>

          {role === "organizer" && (
            <div className="field">
              <label className="label" htmlFor="organizerPassword">
                Organizer Password
              </label>
              <input
                id="organizerPassword"
                type="password"
                className="input"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  setPasswordError("");
                }}
                placeholder="Enter organizer password"
              />
              {passwordError && <span className="error">{passwordError}</span>}
            </div>
          )}

          <button
            className="btn btn--primary"
            type="button"
            onClick={handleJoin}
            disabled={isJoining || !displayName.trim() || (role === "participant" && !urlSessionId)}
            style={{ width: "100%", marginTop: "8px" }}
          >
            {isJoining 
              ? "Connecting..." 
              : urlSessionId 
                ? "Join session" 
                : role === "organizer" 
                  ? "Create & Join Session" 
                  : "Join session"}
          </button>

          <p className="help">
            Make sure you have these services running:
            <br />
            <code>make dev-api</code> (API server)
            <br />
            <code>make dev-agent</code> (AI Moderator)
          </p>
        </div>
      </div>
    </div>
  );
};

export default JoinPage;
