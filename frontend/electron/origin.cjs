function resolveApiOrigin(env = process.env) {
  if (env.OPENBOT_API_URL) return env.OPENBOT_API_URL;
  if (env.OPENBOT_URL?.startsWith("http")) return new URL(env.OPENBOT_URL).origin;
  return `http://127.0.0.1:${env.OPENBOT_BACKEND_PORT || "8000"}`;
}

module.exports = { resolveApiOrigin };
