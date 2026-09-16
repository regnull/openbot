/**
 * Opens an OS directory chooser dialog and returns the selected directory path.
 *
 * Uses the File System Access API (`showDirectoryPicker`) when available,
 * otherwise falls back to a hidden `<input webkitdirectory>` element.
 *
 * Returns the directory name (not the full path) because the browser cannot
 * expose the full filesystem path for security reasons.
 * The working directory is relative to the workspace root.
 */
export type BrowseResult = { path: string } | null;

/**
 * Opens a directory chooser dialog and returns the selected directory name.
 * The user can edit the path manually if the selected directory is not
 * at the workspace root.
 */
export async function browseDirectory(): Promise<BrowseResult> {
  // Try File System Access API first (Chrome, Edge, etc.)
  if (typeof window !== "undefined" && "showDirectoryPicker" in window) {
    try {
      const dirHandle = await (window as any).showDirectoryPicker({ mode: "read" });
      // showDirectoryPicker returns a handle with a `name` property
      return { path: dirHandle.name };
    } catch (e: any) {
      // User cancelled or error
      if (e?.name === "AbortError") {
        return null;
      }
      // Fall through to fallback
    }
  }

  // Fallback: use hidden input element with webkitdirectory
  return new Promise<BrowseResult>((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.setAttribute("webkitdirectory", "");
    input.setAttribute("directory", "");
    input.style.display = "none";
    document.body.appendChild(input);

    const cleanup = () => {
      if (input.parentNode) {
        document.body.removeChild(input);
      }
    };

    input.addEventListener("change", () => {
      const files = input.files;
      if (files && files.length > 0) {
        // Get the directory path from the first file's webkitRelativePath
        const relativePath = (files[0] as any).webkitRelativePath;
        if (relativePath) {
          // Extract directory part (everything before the filename)
          const pathParts = relativePath.split("/");
          pathParts.pop(); // Remove the filename
          const dirPath = pathParts.join("/");
          resolve({ path: dirPath });
        } else {
          resolve(null);
        }
      } else {
        resolve(null);
      }
      cleanup();
    });

    input.addEventListener("cancel", () => {
      resolve(null);
      cleanup();
    });

    input.click();
  });
}
