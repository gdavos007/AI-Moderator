import type { SessionStatus } from "../types";

type ApiSession = {
  id: string;
  roomName: string;
  status: SessionStatus;
};

type JoinResponse = {
  token: string;
  sessionId: string;
  roomName: string;
  identity: string;
  isOrganizer: boolean;
  livekitUrl?: string;
};

// Custom error class for session not found
export class SessionNotFoundError extends Error {
  constructor(sessionId: string) {
    super(`Session not found: ${sessionId}`);
    this.name = "SessionNotFoundError";
  }
}

// Use port 8000 for Python FastAPI server
const apiBaseUrl = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export const createSession = async (roomName: string): Promise<ApiSession> => {
  const response = await fetch(`${apiBaseUrl}/api/sessions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ roomName })
  });

  if (!response.ok) {
    throw new Error("Failed to create session");
  }

  return response.json() as Promise<ApiSession>;
};

export const getSession = async (sessionId: string): Promise<ApiSession> => {
  const response = await fetch(`${apiBaseUrl}/api/sessions/${sessionId}`);

  // Handle 404 specifically - session doesn't exist
  if (response.status === 404) {
    throw new SessionNotFoundError(sessionId);
  }

  if (!response.ok) {
    throw new Error("Failed to get session");
  }

  return response.json() as Promise<ApiSession>;
};

export const joinSession = async (
  sessionId: string,
  displayName: string,
  email: string | undefined,
  isOrganizer: boolean
): Promise<JoinResponse> => {
  const response = await fetch(`${apiBaseUrl}/api/sessions/${sessionId}/join`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      displayName,
      email: email || undefined,
      isOrganizer
    })
  });

  // Handle 404 specifically - session doesn't exist
  if (response.status === 404) {
    throw new SessionNotFoundError(sessionId);
  }

  if (!response.ok) {
    throw new Error("Failed to join session");
  }

  return response.json() as Promise<JoinResponse>;
};

export const startSession = async (sessionId: string) => {
  const response = await fetch(`${apiBaseUrl}/api/sessions/${sessionId}/start`, {
    method: "POST"
  });

  // Handle 404 specifically
  if (response.status === 404) {
    throw new SessionNotFoundError(sessionId);
  }

  if (!response.ok) {
    throw new Error("Failed to start session");
  }

  return response.json();
};

export const endSession = async (sessionId: string) => {
  const response = await fetch(`${apiBaseUrl}/api/sessions/${sessionId}/end`, {
    method: "POST"
  });

  // Handle 404 specifically
  if (response.status === 404) {
    throw new SessionNotFoundError(sessionId);
  }

  if (!response.ok) {
    throw new Error("Failed to end session");
  }

  return response.json();
};

export type SessionStatusResponse = {
  sessionId: string;
  roomName: string;
  status: SessionStatus;
  agentJoined: boolean;
  agentIdentity: string | null;
  participantCount: number;
  livekitParticipants: string[];
};

export const getSessionStatus = async (sessionId: string): Promise<SessionStatusResponse> => {
  const response = await fetch(`${apiBaseUrl}/api/sessions/${sessionId}/status`);

  if (response.status === 404) {
    throw new SessionNotFoundError(sessionId);
  }

  if (!response.ok) {
    throw new Error("Failed to get session status");
  }

  return response.json() as Promise<SessionStatusResponse>;
};
