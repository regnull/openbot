import { expect, test } from "vitest";
import { parseTs } from "./time";

test("reads a naive datetime as UTC", () => {
  expect(parseTs("2026-09-14T03:54:15.536421").toISOString()).toBe("2026-09-14T03:54:15.536Z");
});

test("keeps an explicit zone", () => {
  expect(parseTs("2026-09-14T03:54:15.536Z").toISOString()).toBe("2026-09-14T03:54:15.536Z");
  expect(parseTs("2026-09-14T05:54:15.536+02:00").toISOString()).toBe("2026-09-14T03:54:15.536Z");
});
