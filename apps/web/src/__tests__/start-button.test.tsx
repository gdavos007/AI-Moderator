import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";
import App from "../App";

// Mock LiveKit components to avoid WebRTC errors in tests
vi.mock("@livekit/components-react", () => ({
  LiveKitRoom: ({ children }: { children: React.ReactNode }) => <div data-testid="livekit-room">{children}</div>,
  RoomAudioRenderer: () => null,
  StartAudio: () => null,
  useRoomContext: () => ({ name: "test-room" }),
  useParticipants: () => [],
  useConnectionState: () => "connected",
  useTracks: () => [],
  TrackLoop: () => null,
  ParticipantTile: () => null,
  GridLayout: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ControlBar: () => null,
}));

vi.mock("livekit-client", () => ({
  Track: { Source: { Camera: "camera", ScreenShare: "screen_share", Microphone: "microphone" } },
  ConnectionState: { Connected: "connected" },
}));

const createMockFetch = () => {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();

    if (url.includes("/api/sessions") && !url.includes("/join") && !url.includes("/start") && !url.includes("/status")) {
      // Create session
      return new Response(JSON.stringify({ 
        id: "session-1", 
        roomName: "leverai-demo", 
        status: "waiting",
        agentJoined: false,
      }), { status: 200 });
    }

    if (url.includes("/join")) {
      // Join session - check if organizer from request body
      const body = init?.body ? JSON.parse(init.body as string) : {};
      return new Response(JSON.stringify({
        token: "test-token",
        sessionId: "session-1",
        roomName: "leverai-demo",
        identity: body.isOrganizer ? "organizer_1" : "participant_1",
        isOrganizer: body.isOrganizer || false,
        livekitUrl: "wss://test.livekit.cloud",
      }), { status: 200 });
    }

    if (url.includes("/status")) {
      return new Response(JSON.stringify({
        sessionId: "session-1",
        roomName: "leverai-demo",
        status: "waiting",
        agentJoined: false,
        participantCount: 1,
        livekitParticipants: [],
      }), { status: 200 });
    }

    if (url.includes("/start")) {
      return new Response(JSON.stringify({
        id: "session-1",
        roomName: "leverai-demo",
        status: "in_session",
        agentConfirmed: true,
      }), { status: 200 });
    }

    return new Response(JSON.stringify({}), { status: 200 });
  });
};

describe("Organizer-only Start button", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", createMockFetch());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows Start for organizer", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByPlaceholderText("Your name"), "Avery");
    await user.click(screen.getByRole("button", { name: "Organizer" }));
    await user.click(screen.getByRole("button", { name: /join session/i }));

    // Wait for the session page and Start button
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /start session/i })).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it("hides Start for participants", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByPlaceholderText("Your name"), "Riley");
    await user.click(screen.getByRole("button", { name: "Participant" }));
    await user.click(screen.getByRole("button", { name: /join session/i }));

    // Wait for session page to load
    await waitFor(() => {
      // Check we're on the session page (not join page)
      expect(screen.queryByPlaceholderText("Your name")).not.toBeInTheDocument();
    }, { timeout: 3000 });

    // Start button should not be visible for participants
    expect(screen.queryByRole("button", { name: /start session/i })).not.toBeInTheDocument();
  });
});
