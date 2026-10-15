import { describe, expect, it } from "vitest";
import { applyMention, mentionQuery, parseMentions } from "./mentions";

describe("mentions", () => {
  it("parses unique handles in order", () => {
    expect(parseMentions("hi @eng and @rev, @eng")).toEqual(["eng", "rev"]);
    expect(parseMentions("me@example.com")).toEqual([]);
  });
  it("accepts a trailing sentence period but not a file-extension-like suffix", () => {
    expect(parseMentions("See @eng.")).toEqual(["eng"]);
    expect(parseMentions("read @eng.txt")).toEqual([]);
  });
  it("finds the mention being typed", () => {
    expect(mentionQuery("hello @en", 9)).toEqual({ start: 6, query: "en" });
    expect(mentionQuery("hello @eng done", 15)).toBeNull();
    expect(mentionQuery("@", 1)).toEqual({ start: 0, query: "" });
  });
  it("applies a mention", () => {
    expect(applyMention("hello @en", 6, 9, "eng")).toEqual({ text: "hello @eng ", caret: 11 });
  });
});
