import {
  GridLayout,
  ParticipantTile,
  useTracks,
  TrackRefContext,
} from "@livekit/components-react";
import { Track } from "livekit-client";

type TilesViewProps = {
  agentIdentityHint?: string;
};

const TilesView = ({ agentIdentityHint }: TilesViewProps) => {
  // Only request Camera tracks to prevent duplicate tiles
  // ScreenShare removed since we're not using screen sharing
  const tracks = useTracks(
    [
      { source: Track.Source.Camera, withPlaceholder: true },
    ],
    { onlySubscribed: false }
  );

  const isAgentParticipant = (identity: string) => {
    if (agentIdentityHint && identity === agentIdentityHint) return true;
    const lower = identity.toLowerCase();
    return lower.includes("agent") || lower.includes("moderator");
  };

  return (
    <div className="lk-grid-layout-wrapper">
      <GridLayout tracks={tracks}>
        <TrackRefContext.Consumer>
          {(trackRef) => {
            if (!trackRef) return null;
            const participant = trackRef.participant;
            const identity = participant.identity;
            const name = participant.name || identity;
            const isLocal = participant.isLocal;
            const isSpeaking = participant.isSpeaking;
            const isAgent = isAgentParticipant(identity);
            const isMicEnabled = participant.isMicrophoneEnabled;

            return (
              <div className={`zoom-tile ${isSpeaking ? "zoom-tile--speaking" : ""}`}>
                <ParticipantTile />
                <div className="zoom-namepill">
                  {name}
                  {isAgent && " 🤖"}
                  {isLocal && " (You)"}
                </div>
                {!isMicEnabled && (
                  <div className="zoom-badge">🔇</div>
                )}
              </div>
            );
          }}
        </TrackRefContext.Consumer>
      </GridLayout>
    </div>
  );
};

export default TilesView;
