import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { browseDirectory } from "./browseDirectory";

// Tests run in the plain Node environment (see vite.config.ts), so the browser
// globals that browseDirectory touches are stubbed here per test.
type Listener = (event: string, handler: () => void) => void;

function makeMockInput(addEventListener: Listener) {
  return {
    type: "",
    setAttribute: vi.fn(),
    style: { display: "" },
    click: vi.fn(),
    addEventListener,
    files: null as FileList | null,
    parentNode: null as unknown,
  };
}

describe("browseDirectory", () => {
  let windowStub: Record<string, unknown>;

  beforeEach(() => {
    windowStub = {};
    vi.stubGlobal("window", windowStub);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns null when user cancels File System Access API", async () => {
    windowStub.showDirectoryPicker = vi
      .fn()
      .mockRejectedValue(new DOMException("User cancelled", "AbortError"));
    expect(await browseDirectory()).toBeNull();
  });

  it("returns directory name when user selects via File System Access API", async () => {
    windowStub.showDirectoryPicker = vi.fn().mockResolvedValue({ name: "my-project" });
    expect(await browseDirectory()).toEqual({ path: "my-project" });
  });

  it("returns null when fallback input is cancelled", async () => {
    // No showDirectoryPicker on window forces the <input webkitdirectory> fallback.
    const addEventListener = vi.fn<Listener>();
    const body = { appendChild: vi.fn(), removeChild: vi.fn() };
    const input = makeMockInput(addEventListener);
    input.parentNode = body;
    vi.stubGlobal("document", { createElement: vi.fn().mockReturnValue(input), body });

    const promise = browseDirectory();

    const cancelCall = addEventListener.mock.calls.find(([event]) => event === "cancel");
    expect(cancelCall).toBeDefined();
    cancelCall![1]();

    expect(await promise).toBeNull();
    expect(body.removeChild).toHaveBeenCalledWith(input);
  });

  it("returns the directory part of webkitRelativePath when fallback input changes", async () => {
    const addEventListener = vi.fn<Listener>();
    const body = { appendChild: vi.fn(), removeChild: vi.fn() };
    const input = makeMockInput(addEventListener);
    input.parentNode = body;
    vi.stubGlobal("document", { createElement: vi.fn().mockReturnValue(input), body });

    const promise = browseDirectory();

    input.files = [{ webkitRelativePath: "my-project/src/index.ts" }] as unknown as FileList;
    const changeCall = addEventListener.mock.calls.find(([event]) => event === "change");
    expect(changeCall).toBeDefined();
    changeCall![1]();

    expect(await promise).toEqual({ path: "my-project/src" });
  });
});
