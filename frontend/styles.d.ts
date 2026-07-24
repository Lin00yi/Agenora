/**
 * Lets TypeScript tooling resolve global stylesheet side-effect imports such as
 * `import "./globals.css"` in the App Router layout.
 */
declare module "*.css";
