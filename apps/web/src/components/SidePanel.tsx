import { useState } from "react";
import { useParticipants } from "@livekit/components-react";
import type { GuideItem, SessionStatus, Role } from "../types";
import RosterPanel from "./RosterPanel";
import GuidePanel from "./GuidePanel";

type SidePanelProps = {
  role: Role;
  sessionStatus: SessionStatus;
  guideItems: GuideItem[];
  guideIndex: number;
  onPrevGuide: () => void;
  onNextGuide: () => void;
  agentIdentityHint?: string;
};

type TabId = "participants" | "guide";

const SidePanel = ({
  role,
  sessionStatus,
  guideItems,
  guideIndex,
  onPrevGuide,
  onNextGuide,
  agentIdentityHint,
}: SidePanelProps) => {
  const [activeTab, setActiveTab] = useState<TabId>("participants");
  const participants = useParticipants();

  // If organizer switches to guide tab but no longer organizer, reset
  const effectiveTab = activeTab === "guide" && role !== "organizer" ? "participants" : activeTab;

  return (
    <div className="panel-card" style={{ flex: 1, minHeight: 0 }}>
      <div className="panel-card__header">
        <div className="tabs" style={{ flex: 1 }}>
          <div
            className={`tab ${effectiveTab === "participants" ? "tab--active" : ""}`}
            onClick={() => setActiveTab("participants")}
          >
            Participants ({participants.length})
          </div>
          {role === "organizer" && (
            <div
              className={`tab ${effectiveTab === "guide" ? "tab--active" : ""}`}
              onClick={() => setActiveTab("guide")}
            >
              Guide
            </div>
          )}
        </div>
      </div>

      {effectiveTab === "participants" && (
        <RosterPanel agentIdentityHint={agentIdentityHint} />
      )}

      {effectiveTab === "guide" && role === "organizer" && (
        <GuidePanel
          guideItems={guideItems}
          guideIndex={guideIndex}
          sessionStatus={sessionStatus}
          role={role}
          onPrev={onPrevGuide}
          onNext={onNextGuide}
        />
      )}
    </div>
  );
};

export default SidePanel;
