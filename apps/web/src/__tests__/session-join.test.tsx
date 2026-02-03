import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";
import App from "../App";

// Mock LiveKit components to avoid WebRTC errors in tests
vi.mock("@livekit/components-react", () => ({
  LiveKitRoom: ({ children }: { children: React.ReactNode }) => <div data-testid="livekit-room">{children}</div>,
  RoomAudioRenderer: () => null,
  StartAudio: () => null,
  useRoomContext: () => ({ name: "test-room", localParticipant: { identity: "test-user" } }),
  useParticipants: () => [],
  useConnectionState: () => "connected",
  useTracks: () => [],
  TrackLoop: () => null,
  ParticipantTile: () => null,
  GridLayout: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ControlBar: () => null,
  TrackRefContext: { Consumer: ({ children }: { children: () => React.ReactNode }) => null },
}));

vi.mock("livekit-client", () => ({
  Track: { Source: { Camera: "camera", ScreenShare: "screen_share", Microphone: "microphone" } },
  ConnectionState: { Connected: "connected" },
}));

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

// Mock window.history.replaceState to avoid DOMException in tests
const mockHistoryReplaceState = () => {
  vi.spyOn(window.history, "replaceState").mockImplementation(() => {});
};

const createMockFetch = () => {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();

    // Create session endpoint
    if (url.match(/\/api\/sessions$/) && init?.method === "POST") {
      return new Response(JSON.stringify({ 
        id: "new-session-123", 
        roomName: "focusgroup-test-new-session-123", 
        status: "waiting",
      }), { status: 200 });
    }

    // Get session endpoint
    if (url.match(/\/api\/sessions\/[^/]+$/) && (!init?.method || init?.method === "GET")) {
      const sessionId = url.split("/").pop();
      return new Response(JSON.stringify({ 
        id: sessionId, 
        roomName: `focusgroup-test-${sessionId}`, 
        status: "waiting",
      }), { status: 200 });
    }

    // Join session endpoint
    if (url.includes("/join")) {
      const body = init?.body ? JSON.parse(init.body as string) : {};
      const sessionId = url.split("/")[url.split("/").length - 2];
      return new Response(JSON.stringify({
        token: "test-token",
        sessionId: sessionId,
        roomName: `focusgroup-test-${sessionId}`,
        identity: body.isOrganizer ? "organizer_1" : "participant_1",
        isOrganizer: body.isOrganizer || false,
        livekitUrl: "wss://test.livekit.cloud",
      }), { status: 200 });
    }

    // Status endpoint
    if (url.includes("/status")) {
      return new Response(JSON.stringify({
        sessionId: "test-session",
        roomName: "focusgroup-test",
        status: "waiting",
        agentJoined: false,
        participantCount: 1,
        livekitParticipants: [],
      }), { status: 200 });
    }

    return new Response(JSON.stringify({}), { status: 200 });
  });
};

describe("Session Join Flow - URL-based sharing", () => {
  let mockFetch: ReturnType<typeof createMockFetch>;

  beforeEach(() => {
    mockFetch = createMockFetch();
    vi.stubGlobal("fetch", mockFetch);
    // Mock history.replaceState to avoid DOMException
    mockHistoryReplaceState();
    // Reset URL to no session
    setUrlWithSession(null);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  describe("Participant without URL session", () => {
    it("shows warning message for participant without session URL", async () => {
      render(<App />);
      
      const user = userEvent.setup();
      
      // Switch to participant role
      await user.click(screen.getByRole("button", { name: "Participant" }));
      
      // Should see warning about needing a session link (match actual text in JoinPage)
      expect(screen.getByText(/you need a session link from the organizer/i)).toBeInTheDocument();
    });

    it("disables join button for participant without session URL", async () => {
      render(<App />);
      
      const user = userEvent.setup();
      
      // Enter name and switch to participant
      await user.type(screen.getByPlaceholderText("Your name"), "TestUser");
      await user.click(screen.getByRole("button", { name: "Participant" }));
      
      // Join button should be disabled
      const joinButton = screen.getByRole("button", { name: /join session/i });
      expect(joinButton).toBeDisabled();
    });

    it("does NOT call createSession when participant has no URL session", async () => {
      render(<App />);
      
      const user = userEvent.setup();
      
      // Try to join as participant without URL session
      await user.type(screen.getByPlaceholderText("Your name"), "TestUser");
      await user.click(screen.getByRole("button", { name: "Participant" }));
      
      // Button is disabled, so no API calls should be made
      // Verify createSession was never called
      const createCalls = mockFetch.mock.calls.filter(
        ([url]) => typeof url === "string" && url.match(/\/api\/sessions$/)
      );
      expect(createCalls.length).toBe(0);
    });
  });

  describe("Participant with URL session", () => {
    beforeEach(() => {
      // Set URL with session parameter
      setUrlWithSession("existing-session-abc");
    });

    it("shows info banner when joining via shared link", async () => {
      render(<App />);
      
      // Should see info message about joining existing session
      expect(screen.getByText(/joining an existing session/i)).toBeInTheDocument();
    });

    it("defaults to participant role when URL has session", async () => {
      render(<App />);
      
      // Participant button should be active
      const participantBtn = screen.getByRole("button", { name: "Participant" });
      expect(participantBtn).toHaveAttribute("aria-pressed", "true");
    });

    it("does NOT call createSession when joining via URL", async () => {
      render(<App />);
      
      const user = userEvent.setup();
      
      // Join as participant via URL
      await user.type(screen.getByPlaceholderText("Your name"), "TestParticipant");
      await user.click(screen.getByRole("button", { name: /join session/i }));
      
      // Wait for join to complete
      await waitFor(() => {
        expect(screen.getByTestId("livekit-room")).toBeInTheDocument();
      }, { timeout: 3000 });
      
      // Verify createSession was NOT called
      const createCalls = mockFetch.mock.calls.filter(
        ([url, init]) => 
          typeof url === "string" && 
          url.match(/\/api\/sessions$/) && 
          init?.method === "POST"
      );
      expect(createCalls.length).toBe(0);
      
      // Verify joinSession WAS called with the URL session ID
      const joinCalls = mockFetch.mock.calls.filter(
        ([url]) => typeof url === "string" && url.includes("/join")
      );
      expect(joinCalls.length).toBe(1);
      expect(joinCalls[0][0]).toContain("existing-session-abc");
    });
  });

  describe("Organizer creating new session", () => {
    it("calls createSession when organizer has no URL session", async () => {
      render(<App />);
      
      const user = userEvent.setup();
      
      // Join as organizer (default role when no URL session)
      await user.type(screen.getByPlaceholderText("Your name"), "TestOrganizer");
      await user.type(screen.getByLabelText(/organizer password/i), "ABC12345!");
      await user.click(screen.getByRole("button", { name: /create.*join/i }));
      
      // Wait for session page
      await waitFor(() => {
        expect(screen.getByTestId("livekit-room")).toBeInTheDocument();
      }, { timeout: 3000 });
      
      // Verify createSession WAS called
      const createCalls = mockFetch.mock.calls.filter(
        ([url, init]) => 
          typeof url === "string" && 
          url.match(/\/api\/sessions$/) && 
          init?.method === "POST"
      );
      expect(createCalls.length).toBe(1);
    });
  });
});
