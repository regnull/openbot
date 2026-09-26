/** The packaged Electron app loads the build from file://, where only the URL hash can carry the route. */
export const usesHashRouting = (protocol: string): boolean => protocol === "file:";

/** Public assets resolve against Vite's base: "/" for the browser build, "./" for the Electron build. */
export const logoSrc = `${import.meta.env.BASE_URL}logo-icon.svg`;
