import type { Participant } from "../types";

export type RaiseHandEvent = {
  version: "v1";
  type: "raise_hand";
  sessionId: string;
  participantId: string;
  participantName: string;
  createdAt: string;
};

const apiBaseUrl = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export const createRaiseHandEvent = (
  sessionId: string,
  participant: Participant
): RaiseHandEvent => ({
  version: "v1",
  type: "raise_hand",
  sessionId,
  participantId: participant.id,
  participantName: participant.name,
  createdAt: new Date().toISOString()
});

export const sendRaiseHandEvent = async (event: RaiseHandEvent) => {
  await fetch(`${apiBaseUrl}/api/sessions/${event.sessionId}/raise-hand`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(event)
  });
};
