/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  typedRoutes: false,
  // Keep Turbopack scoped to this checkout; a parent pnpm lockfile must not
  // change dependency-root detection during local or Docker builds.
  turbopack: { root: __dirname },
  // Docker: standalone build copies only what server.js needs into .next/standalone,
  // shrinking the runner image from ~500MB to ~150MB. `next dev` and `next start`
  // still work as before — this only adds an extra output folder.
  output: "standalone",
};
module.exports = nextConfig;
