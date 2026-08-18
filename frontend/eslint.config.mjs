import nextCoreWebVitals from "eslint-config-next/core-web-vitals";

// These React Compiler diagnostics were introduced by the Next 16 preset.
// They were not part of the project's prior CI contract; migrate each call
// site deliberately rather than making this security dependency update a
// behavior-changing rewrite of the entire UI.
const config = [
  ...nextCoreWebVitals,
  {
    rules: {
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/refs": "off",
      "react-hooks/purity": "off",
    },
  },
  {
    ignores: [".next/**", "node_modules/**", "coverage/**"],
  },
];

export default config;
