// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { setOpenBotTitle } from "./documentTitle";

describe("setOpenBotTitle", () => {
  afterEach(() => {
    document.title = "";
  });

  it("uses the app name alone when no page is given", () => {
    setOpenBotTitle();
    expect(document.title).toBe("OpenBot");
  });

  it("prefixes a page or thread name", () => {
    setOpenBotTitle("Planning the launch");
    expect(document.title).toBe("Planning the launch — OpenBot");
  });

  it("ignores blank labels", () => {
    setOpenBotTitle("   ");
    expect(document.title).toBe("OpenBot");
  });
});
