import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, describe, it, expect, beforeEach, afterEach } from "vitest";
import App from "../App";

// Mock LiveKit components to avoid WebRTC errors in tests
vi.mock("@livekit/components-react", () => ({
  LiveKitRoom: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="livekit-room">{children}</div>
  ),
  RoomAudioRenderer: () => null,
  StartAudio: () => null,
  useRoomContext: () => ({ name: "test-room" }),
  useParticipants: () => [
    {
      sid: "local-sid",
      identity: "organizer_1",
      name: "Organizer",
      isLocal: true,
      isSpeaking: false,
      isMicrophoneEnabled: true,
    },
  ],
  useConnectionState: () => "connected",
  useTracks: () => [
    {
      participant: {
        sid: "local-sid",
        identity: "organizer_1",
        name: "Organizer",
        isLocal: true,
        isSpeaking: false,
        isMicrophoneEnabled: true,
      },
      source: "camera",
    },
  ],
  TrackLoop: () => null,
  ParticipantTile: () => <div data-testid="participant-tile">Tile</div>,
  GridLayout: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="grid-layout">{children}</div>
  ),
  ControlBar: () => null,
  TrackRefContext: {
    Consumer: ({ children }: { children: (trackRef: unknown) => React.ReactNode }) =>
      children({
        participant: {
          sid: "local-sid",
          identity: "organizer_1",
          name: "Organizer",
          isLocal: true,
          isSpeaking: false,
          isMicrophoneEnabled: true,
        },
        source: "camera",
      }),
  },
}));

vi.mock("livekit-client", () => ({
  Track: {
    Source: { Camera: "camera", ScreenShare: "screen_share", Microphone: "microphone" },
  },
  ConnectionState: { Connected: "connected" },
}));

// Helper to reset URL (no session parameter)
const resetUrlWithoutSession = () => {
  const url = new URL("http://localhost:5173");
  Object.defineProperty(window, "location", {
    value: {
      ...window.location,
      href: url.toString(),
      search: "",
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

    if (
      url.includes("/api/sessions") &&
      !url.includes("/join") &&
      !url.includes("/start") &&
      !url.includes("/status")
    ) {
      // Create session - returns WAITING status
      return new Response(
        JSON.stringify({
          id: "session-1",
          roomName: "leverai-demo",
          status: "waiting", // <-- Session status is WAITING
          agentJoined: false,
        }),
        { status: 200 }
      );
    }

    if (url.includes("/join")) {
      const body = init?.body ? JSON.parse(init.body as string) : {};
      return new Response(
        JSON.stringify({
          token: "test-token",
          sessionId: "session-1",
          roomName: "leverai-demo",
          identity: body.isOrganizer ? "organizer_1" : "participant_1",
          isOrganizer: body.isOrganizer || false,
          livekitUrl: "wss://test.livekit.cloud",
        }),
        { status: 200 }
      );
    }

    if (url.includes("/status")) {
      return new Response(
        JSON.stringify({
          sessionId: "session-1",
          roomName: "leverai-demo",
          status: "waiting", // <-- Still waiting
          agentJoined: false,
          participantCount: 1,
          livekitParticipants: [],
        }),
        { status: 200 }
      );
    }

    return new Response(JSON.stringify({}), { status: 200 });
  });
};

describe("TilesView during waiting status", () => {
  beforeEach(() => {
    // Reset URL to have no session (organizer creates new session)
    resetUrlWithoutSession();
    // Mock history.replaceState to avoid DOMException
    mockHistoryReplaceState();
    vi.stubGlobal("fetch", createMockFetch());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders tiles container when session status is waiting", async () => {
    const user = userEvent.setup();
    render(<App />);

    // Fill in name and enter organizer password (organizer is default when no URL session)
    await user.type(screen.getByPlaceholderText("Your name"), "TestOrganizer");
    await user.type(screen.getByLabelText(/organizer password/i), "ABC12345!");
    await user.click(screen.getByRole("button", { name: /create.*join/i }));

    // Wait for session page to load
    await waitFor(
      () => {
        expect(screen.getByTestId("livekit-room")).toBeInTheDocument();
      },
      { timeout: 3000 }
    );

    // Verify the "Waiting" banner is shown (proves status is waiting)
    expect(screen.getByText(/waiting for organizer to start/i)).toBeInTheDocument();

    // Verify the tiles grid layout exists even in waiting state
    expect(screen.getByTestId("grid-layout")).toBeInTheDocument();

    // Verify the Leave button exists (we're on session page)
    expect(screen.getByRole("button", { name: /leave/i })).toBeInTheDocument();

    // Verify Start session button exists (organizer can start)
    expect(screen.getByRole("button", { name: /start session/i })).toBeInTheDocument();
  });

  it("renders local participant tile placeholder during waiting", async () => {
    const user = userEvent.setup();
    render(<App />);

    // Fill in name and enter organizer password (organizer is default when no URL session)
    await user.type(screen.getByPlaceholderText("Your name"), "TestOrganizer");
    await user.type(screen.getByLabelText(/organizer password/i), "ABC12345!");
    await user.click(screen.getByRole("button", { name: /create.*join/i }));

    // Wait for session page
    await waitFor(
      () => {
        expect(screen.getByTestId("livekit-room")).toBeInTheDocument();
      },
      { timeout: 3000 }
    );

    // Verify tiles wrapper exists (lk-grid-layout-wrapper class is used in TilesView)
    const gridLayout = screen.getByTestId("grid-layout");
    expect(gridLayout).toBeInTheDocument();

    // Verify the waiting status hasn't hidden the tiles area
    // The zoom-stage should be visible (no hidden class)
    const stage = document.querySelector(".zoom-stage");
    expect(stage).toBeInTheDocument();
    expect(stage).not.toHaveClass("hidden-mobile");
  });
});
