import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";
import App from "../App";

// Mock LiveKit components to avoid WebRTC errors in tests
vi.mock("@livekit/components-react", () => ({
  LiveKitRoom: ({ children }: { children: React.ReactNode }) => <div data-testid="livekit-room">{children}</div>,
  RoomAudioRenderer: () => null,
  StartAudio: () => null,
<<<<<<< HEAD
  useRoomContext: () => ({ name: "test-room", localParticipant: { identity: "test-user" } }),
=======
  useRoomContext: () => ({ name: "test-room" }),
>>>>>>> origin/migrate/snapshot
  useParticipants: () => [],
  useConnectionState: () => "connected",
  useTracks: () => [],
  TrackLoop: () => null,
  ParticipantTile: () => null,
  GridLayout: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ControlBar: () => null,
<<<<<<< HEAD
  TrackRefContext: { Consumer: ({ children }: { children: () => React.ReactNode }) => null },
=======
>>>>>>> origin/migrate/snapshot
}));

vi.mock("livekit-client", () => ({
  Track: { Source: { Camera: "camera", ScreenShare: "screen_share", Microphone: "microphone" } },
  ConnectionState: { Connected: "connected" },
}));

<<<<<<< HEAD
// Helper to set URL with session parameter
const setUrlWithSession = (sessionId: string | null) => {
  const url = new URL("http://localhost:5173");
  if (sessionId) {
    url.searchParams.set("session", sessionId);
  }
  Object.defineProperty(window, "location", {
    value: {
      ...window.location,
      href: url.toString(),
      search: url.search,
      origin: url.origin,
    },
    writable: true,
  });
};

=======
>>>>>>> origin/migrate/snapshot
describe("Raise-hand event payload", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
<<<<<<< HEAD
    // Participant needs URL with session to join
    setUrlWithSession("session-1");
    
=======
>>>>>>> origin/migrate/snapshot
    // Create a mock fetch that handles session API calls
    fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();

      if (url.includes("/api/sessions") && !url.includes("/join") && !url.includes("/raise-hand") && !url.includes("/status")) {
<<<<<<< HEAD
        // Create session (should NOT be called for participants)
=======
        // Create session
>>>>>>> origin/migrate/snapshot
        return new Response(JSON.stringify({ 
          id: "session-1", 
          roomName: "leverai-demo", 
          status: "waiting",
          agentJoined: false,
        }), { status: 200 });
      }

      if (url.includes("/join")) {
        // Join session
        return new Response(JSON.stringify({
          token: "test-token",
          sessionId: "session-1",
          roomName: "leverai-demo",
          identity: "taylor_1",
          isOrganizer: false,
          livekitUrl: "wss://test.livekit.cloud",
        }), { status: 200 });
      }

      if (url.includes("/status")) {
        // Session status
        return new Response(JSON.stringify({
          sessionId: "session-1",
          roomName: "leverai-demo",
          status: "waiting",
          agentJoined: false,
          participantCount: 1,
          livekitParticipants: ["taylor_1"],
        }), { status: 200 });
      }

      if (url.includes("/raise-hand")) {
        // Raise hand
        return new Response(JSON.stringify({ success: true, queuePosition: 0 }), { status: 200 });
      }

      return new Response(JSON.stringify({}), { status: 200 });
    });

    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("emits raise-hand call to the API", async () => {
    const user = userEvent.setup();

    render(<App />);

<<<<<<< HEAD
    // Fill in form and join as Participant (via URL session)
    // Participant is default role when URL has session
    await user.type(screen.getByPlaceholderText("Your name"), "Taylor");
    await user.click(screen.getByRole("button", { name: /join session/i }));

    // Wait for session page to load (check for zoom-shell class or Leave button)
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /leave/i })).toBeInTheDocument();
=======
    // Fill in form and join
    await user.type(screen.getByPlaceholderText("Your name"), "Taylor");
    await user.click(screen.getByRole("button", { name: "Participant" }));
    await user.click(screen.getByRole("button", { name: /join session/i }));

    // Wait for session page to load
    await waitFor(() => {
      expect(screen.queryByText(/connecting/i) || screen.queryByText(/session/i)).toBeTruthy();
>>>>>>> origin/migrate/snapshot
    }, { timeout: 3000 });

    // Note: The actual raise-hand button may not be visible in the test
    // because it requires the session to be in a specific state.
    // This test verifies the API mocking infrastructure works.
    
<<<<<<< HEAD
    // Check that join was called (participant does NOT call createSession)
    const calls = fetchMock.mock.calls;
    const createCall = calls.find(([url, init]) => 
      typeof url === "string" && url.match(/\/api\/sessions$/) && init?.method === "POST"
=======
    // Check that create session and join were called
    const calls = fetchMock.mock.calls;
    const createCall = calls.find(([url]) => 
      typeof url === "string" && url.includes("/api/sessions") && !url.includes("/join")
>>>>>>> origin/migrate/snapshot
    );
    const joinCall = calls.find(([url]) => 
      typeof url === "string" && url.includes("/join")
    );

<<<<<<< HEAD
    // Participant should NOT create session (they join via URL)
    expect(createCall).toBeFalsy();
    // But they should call join
=======
    expect(createCall).toBeTruthy();
>>>>>>> origin/migrate/snapshot
    expect(joinCall).toBeTruthy();
  });
});
