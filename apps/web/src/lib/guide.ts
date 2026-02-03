import guide from "../../../../discussion_guide.json";
import type { GuideItem, GuideItemType } from "../types";

type GuideSource = {
  meta: {
    title: string;
    duration_minutes: number;
  };
  sections: Array<{
    id: string;
    title: string;
    script_md?: string;
    questions: Array<{
      id: string;
      type?: GuideItemType;
      text?: string;
      script_md?: string;
    }>;
  }>;
};

const guideSource = guide as GuideSource;

const normalizeType = (type?: GuideItemType): GuideItemType => {
  if (!type) {
    return "question";
  }
  return type;
};

export const getGuideMeta = () => guideSource.meta;

export const getGuideItems = (): GuideItem[] => {
  const items: GuideItem[] = [];

  guideSource.sections.forEach((section) => {
    if (section.script_md) {
      items.push({
        id: `${section.id}__script`,
        sectionId: section.id,
        sectionTitle: section.title,
        type: "script",
        text: section.script_md
      });
    }

    section.questions.forEach((question) => {
      const text = question.text ?? question.script_md ?? "";
      if (!text) {
        return;
      }
      items.push({
        id: question.id,
        sectionId: section.id,
        sectionTitle: section.title,
        type: normalizeType(question.type),
        text
      });
    });
  });

  return items;
};
