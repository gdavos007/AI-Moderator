export type SessionStatus = "waiting" | "in_session" | "ended";

export type Role = "organizer" | "participant";

export type Participant = {
  id: string;
  name: string;
  email?: string;
  role: Role;
  joined: boolean;
  micOn: boolean;
  camOn: boolean;
  handRaised: boolean;
};

export type GuideItemType = "script" | "question" | "info" | "closing" | "rollcall";

export type GuideItem = {
  id: string;
  sectionId: string;
  sectionTitle: string;
  type: GuideItemType;
  text: string;
};
