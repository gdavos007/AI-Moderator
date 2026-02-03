import { ControlBar } from "@livekit/components-react";
import type { SessionStatus, Role } from "../types";

type BottomBarProps = {
  role: Role;
  sessionStatus: SessionStatus;
  onEndSession: () => void;
  onLeave: () => void;
};

const BottomBar = ({ role, sessionStatus, onEndSession, onLeave }: BottomBarProps) => {
  return (
    <>
      <div className="zoom-controls">
        {/* Spacer for left side */}
      </div>

      <div className="zoom-controls">
        <ControlBar variation="minimal" />
      </div>

      <div className="zoom-controls">
        {role === "organizer" && sessionStatus === "in_session" && (
          <button className="btn btn--danger" type="button" onClick={onEndSession}>
            End Session
          </button>
        )}
        <button className="btn" type="button" onClick={onLeave}>
          Leave
        </button>
      </div>
    </>
  );
};

export default BottomBar;
