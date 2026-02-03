import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";
import App from "../App";

// Capture original fetch for debug logging before tests stub it
let realFetch: typeof fetch | undefined;

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
  TrackRefContext: { Consumer: ({ children }: { children: () => React.ReactNode }) => null },
}));

vi.mock("livekit-client", () => ({
  Track: { Source: { Camera: "camera", ScreenShare: "screen_share", Microphone: "microphone" } },
  ConnectionState: { Connected: "connected" },
}));

// Helper to set/reset URL with session parameter
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

const createMockFetch = () => {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    // Allow debug logs to reach ingest endpoint even when fetch is mocked
    if (url.startsWith("http://127.0.0.1:7243/ingest/")) {
      return realFetch
        ? realFetch(input, init)
        : new Response(JSON.stringify({ ok: false, error: "realFetch unavailable" }), { status: 500 });
    }

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

    return new Response(JSON.stringify({}), { status: 200 });
  });
};

describe("Organizer password gate", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    // Reset URL to no session (organizer creates new)
    setUrlWithSession(null);
    // Capture real fetch before stubbing
    realFetch = globalThis.fetch ? globalThis.fetch.bind(globalThis) : undefined;
    // #region agent log
    if (realFetch) {
      realFetch("http://127.0.0.1:7243/ingest/ffdb9e2c-8f96-4bc5-a420-1ae6913ff40a",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sessionId:"debug-session",runId:"run1",hypothesisId:"H0",location:"organizer-password.test.tsx:96",message:"before_stub_fetch",data:{realFetchAvailable:!!realFetch},timestamp:Date.now()})}).catch(()=>{});
    }
    // #endregion
    fetchMock = createMockFetch();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows password field when Organizer role is selected", async () => {
    render(<App />);

    // Organizer is selected by default when no URL session, so password field should be visible
    expect(screen.getByLabelText(/organizer password/i)).toBeInTheDocument();
  });

  it("hides password field for Participant role", async () => {
    const user = userEvent.setup();
    render(<App />);

    // Switch to Participant role
    await user.click(screen.getByRole("button", { name: "Participant" }));

    // Password field should be hidden
    expect(screen.queryByLabelText(/organizer password/i)).not.toBeInTheDocument();
  });

  it("blocks join with wrong password - no API calls made", async () => {
    const user = userEvent.setup();
    render(<App />);

    // Fill in name
    await user.type(screen.getByPlaceholderText("Your name"), "Alex");

    // Make sure Organizer is selected (default when no URL session)
    expect(screen.getByRole("button", { name: "Organizer" })).toHaveClass("join-role-btn--active");

    // Enter wrong password
    await user.type(screen.getByLabelText(/organizer password/i), "wrongpassword");

    // Click join
    await user.click(screen.getByRole("button", { name: /create.*join/i }));

    // Should show error message
    expect(screen.getByText(/invalid organizer password/i)).toBeInTheDocument();

    // No API calls should have been made
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("allows join with correct password - API calls proceed", async () => {
    const user = userEvent.setup();
    render(<App />);

    // Fill in name
    await user.type(screen.getByPlaceholderText("Your name"), "Alex");

    // Make sure Organizer is selected (default when no URL session)
    expect(screen.getByRole("button", { name: "Organizer" })).toHaveClass("join-role-btn--active");

    // Enter correct password
    await user.type(screen.getByLabelText(/organizer password/i), "ABC12345!");

    // Click join
    await user.click(screen.getByRole("button", { name: /create.*join/i }));

    // Should not show password error
    expect(screen.queryByText(/invalid organizer password/i)).not.toBeInTheDocument();

    // API calls should have been made
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });

    // Should have created session
    // #region agent log
    fetch("http://127.0.0.1:7243/ingest/ffdb9e2c-8f96-4bc5-a420-1ae6913ff40a",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sessionId:"debug-session",runId:"run1",hypothesisId:"H1",location:"organizer-password.test.tsx:165",message:"before_createCall_find",data:{mockCalls:fetchMock.mock.calls.length},timestamp:Date.now()})}).catch(()=>{});
    // #endregion
    const createCall = fetchMock.mock.calls.find((call) => {
      const url = call[0];
      return typeof url === "string" && url.includes("/api/sessions") && !url.includes("/join");
    });
    // #region agent log
    fetch("http://127.0.0.1:7243/ingest/ffdb9e2c-8f96-4bc5-a420-1ae6913ff40a",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sessionId:"debug-session",runId:"run1",hypothesisId:"H2",location:"organizer-password.test.tsx:169",message:"after_createCall_find",data:{createCallFound:!!createCall,createCallUrl:typeof createCall?.[0]==="string"?createCall?.[0]:null},timestamp:Date.now()})}).catch(()=>{});
    // #endregion
    expect(createCall).toBeTruthy();
    // #region agent log
    fetch("http://127.0.0.1:7243/ingest/ffdb9e2c-8f96-4bc5-a420-1ae6913ff40a",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sessionId:"debug-session",runId:"run1",hypothesisId:"H3",location:"organizer-password.test.tsx:172",message:"after_expect_createCall_truthy",data:{createCallTruthy:!!createCall},timestamp:Date.now()})}).catch(()=>{});
    // #endregion
  });

  it("participant can join without password when they have a session URL", async () => {
    // Participant needs a URL session to join
    setUrlWithSession("session-1");
    
    const user = userEvent.setup();
    render(<App />);

    // Fill in name (participant is default when URL has session)
    await user.type(screen.getByPlaceholderText("Your name"), "Riley");

    // No password field should be visible
    expect(screen.queryByLabelText(/organizer password/i)).not.toBeInTheDocument();

    // Click join
    await user.click(screen.getByRole("button", { name: /join session/i }));

    // API calls should proceed (join only, no create)
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    
    // Verify only join was called (no create)
    const joinCall = fetchMock.mock.calls.find((call) => {
      const url = call[0];
      return typeof url === "string" && url.includes("/join");
    });
    expect(joinCall).toBeTruthy();
  });
});
