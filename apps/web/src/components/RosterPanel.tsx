import { useParticipants } from "@livekit/components-react";

type RosterPanelProps = {
  agentIdentityHint?: string;
};

const RosterPanel = ({ agentIdentityHint }: RosterPanelProps) => {
  const participants = useParticipants();

  const isAgentParticipant = (identity: string) => {
    if (agentIdentityHint && identity === agentIdentityHint) return true;
    const lower = identity.toLowerCase();
    return lower.includes("agent") || lower.includes("moderator");
  };

  return (
    <div className="panel-card__body">
      {participants.length === 0 ? (
        <p style={{ color: "var(--muted)", fontSize: "13px" }}>No participants yet</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: "8px" }}>
          {participants.map((participant) => {
            const identity = participant.identity;
            const name = participant.name || identity;
            const isLocal = participant.isLocal;
            const isAgent = isAgentParticipant(identity);
            const isSpeaking = participant.isSpeaking;
            const isMicEnabled = participant.isMicrophoneEnabled;

            return (
              <li
                key={participant.sid}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "8px 10px",
                  borderRadius: "10px",
                  background: isSpeaking ? "rgba(79, 124, 255, 0.12)" : "rgba(255, 255, 255, 0.03)",
                  border: `1px solid ${isSpeaking ? "rgba(79, 124, 255, 0.35)" : "var(--border)"}`,
                }}
              >
                <span style={{ fontWeight: 600, fontSize: "13px" }}>
                  {name}
                  {isAgent && " 🤖"}
                  {isLocal && " (You)"}
                </span>
                <span style={{ fontSize: "12px", color: "var(--muted)" }}>
                  {isSpeaking ? "🗣️" : isMicEnabled ? "🎤" : "🔇"}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
};

export default RosterPanel;
