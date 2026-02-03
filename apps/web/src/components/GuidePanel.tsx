import type { GuideItem, SessionStatus, Role } from "../types";

const statusLabels: Record<SessionStatus, string> = {
  waiting: "Waiting to start",
  in_session: "In session",
  ended: "Ended",
};

type GuidePanelProps = {
  guideItems: GuideItem[];
  guideIndex: number;
  sessionStatus: SessionStatus;
  role: Role;
  onPrev: () => void;
  onNext: () => void;
};

const GuidePanel = ({
  guideItems,
  guideIndex,
  sessionStatus,
  role,
  onPrev,
  onNext,
}: GuidePanelProps) => {
  const currentGuideItem = guideItems[guideIndex];

  // Participant cannot see guide content
  if (role !== "organizer") {
    return (
      <div className="panel-card__body">
        <p style={{ color: "var(--muted)", fontSize: "13px" }}>
          Guide is only visible to the organizer.
        </p>
      </div>
    );
  }

  if (sessionStatus === "waiting") {
    return (
      <div className="panel-card__body">
        <p style={{ color: "var(--muted)", fontSize: "13px" }}>
          {statusLabels[sessionStatus]}
        </p>
        <p style={{ color: "var(--muted-2)", fontSize: "12px", marginTop: "8px" }}>
          Start the session to begin the moderated flow.
        </p>
      </div>
    );
  }

  if (!currentGuideItem) {
    return (
      <div className="panel-card__body">
        <p style={{ color: "var(--muted)", fontSize: "13px" }}>No guide items available.</p>
      </div>
    );
  }

  return (
    <div className="panel-card__body">
      <div
        style={{
          background: "rgba(0, 0, 0, 0.25)",
          borderRadius: "12px",
          padding: "12px",
          border: "1px solid var(--border)",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: "8px",
          }}
        >
          <span style={{ fontSize: "12px", color: "var(--muted)" }}>
            {currentGuideItem.sectionTitle}
          </span>
          <span style={{ fontSize: "12px", color: "var(--muted)" }}>
            {guideIndex + 1} / {guideItems.length}
          </span>
        </div>

        <p
          style={{
            textTransform: "uppercase",
            fontSize: "10px",
            letterSpacing: "0.08em",
            color: "var(--accent)",
            marginBottom: "8px",
          }}
        >
          {currentGuideItem.type}
        </p>

        <p style={{ fontSize: "14px", lineHeight: "1.5", marginBottom: "12px" }}>
          {currentGuideItem.text}
        </p>

        <div style={{ display: "flex", gap: "8px" }}>
          <button
            className="btn"
            type="button"
            onClick={onPrev}
            disabled={guideIndex === 0}
            style={{ flex: 1 }}
          >
            Previous
          </button>
          <button
            className="btn btn--primary"
            type="button"
            onClick={onNext}
            disabled={guideIndex === guideItems.length - 1}
            style={{ flex: 1 }}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
};

export default GuidePanel;
