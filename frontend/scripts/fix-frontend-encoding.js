/**
 * Fix UTF-8 Chinese text across frontend source files on Windows.
 *
 * Only repairs string literals containing 4+ consecutive '?' (encoding corruption).
 * Does NOT touch JavaScript nullish coalescing (??).
 *
 * Usage: npm run fix:encoding
 */
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const FRONTEND = path.join(__dirname, "..");
const REPO = path.join(FRONTEND, "..");

const SKIP_DIRS = new Set(["node_modules", ".next", "ui", "dist"]);
const SKIP_FILES = new Set([
  "fix-chatbox-encoding.js",
  "fix-frontend-encoding.js",
  "scan-encoding.js",
  "scan-chinese-strings.js",
]);

const BRAND_REPLACEMENTS = [
  [/focus:ring-accent\//g, "focus:ring-brand/"],
  [/focus:border-accent/g, "focus:border-brand"],
  [/hover:bg-accent\//g, "hover:bg-brand/"],
  [/hover:text-accent/g, "hover:text-brand"],
  [/bg-accent\//g, "bg-brand/"],
  [/text-accent\//g, "text-brand/"],
  [/ring-accent\//g, "ring-brand/"],
  [/border-accent\//g, "border-brand/"],
  [/from-accent/g, "from-brand"],
  [/via-accent/g, "via-brand"],
  [/to-accent/g, "to-brand"],
  [/bg-accent(?!-foreground)/g, "bg-brand"],
  [/text-accent(?!-foreground)/g, "text-brand"],
  [/ring-accent/g, "ring-brand"],
  [/border-accent/g, "border-brand"],
];

const CORRUPT_STRING = /(["'`])([^"'`]*\?{4,}[^"'`]*)\1/g;

function walk(dir, acc = []) {
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name);
    const st = fs.statSync(p);
    if (st.isDirectory()) {
      if (!SKIP_DIRS.has(name)) walk(p, acc);
      continue;
    }
    if (/\.(tsx?|jsx?)$/.test(name) && !SKIP_FILES.has(name)) acc.push(p);
  }
  return acc;
}

function toRepoRel(abs) {
  return path.relative(REPO, abs).split(path.sep).join("/");
}

function gitHead(rel) {
  try {
    return execSync(`git show HEAD:${rel}`, {
      cwd: REPO,
      encoding: "utf8",
      maxBuffer: 20 * 1024 * 1024,
    });
  } catch {
    return null;
  }
}

function applyBrandTokens(s) {
  let out = s;
  for (const [re, rep] of BRAND_REPLACEMENTS) out = out.replace(re, rep);
  return out;
}

function extractChineseStrings(src) {
  const out = [];
  const re = /(["'`])((?:\\.|(?!\1)[\s\S])*?)\1/g;
  let m;
  while ((m = re.exec(src))) {
    if (/[\u4e00-\u9fff]/.test(m[2])) out.push(m[2]);
  }
  return [...new Set(out)];
}

function hasCorruptStrings(s) {
  CORRUPT_STRING.lastIndex = 0;
  return CORRUPT_STRING.test(s) || s.includes("\uFFFD");
}

function repairCorruptStrings(current, head) {
  let out = current;
  let changed = false;
  const headStrings = extractChineseStrings(head).sort((a, b) => b.length - a.length);

  CORRUPT_STRING.lastIndex = 0;
  let match;
  while ((match = CORRUPT_STRING.exec(current))) {
    const full = match[0];
    const quote = match[1];
    const corrupt = match[2];

    const replacement = headStrings.find((s) => {
      const headCorrupt = s.replace(/[\u4e00-\u9fff]/g, "?");
      return (
        headCorrupt === corrupt ||
        (corrupt.length >= 4 && s.length === corrupt.length)
      );
    });

    if (replacement) {
      out = out.replace(full, `${quote}${replacement}${quote}`);
      changed = true;
    }
  }

  for (const cn of headStrings) {
    const corrupted = cn.replace(/[\u4e00-\u9fff]/g, "?");
    if (corrupted !== cn && out.includes(`${quote}${corrupted}${quote}`)) {
      // noop - handled above
    }
    if (!out.includes(cn)) {
      const pattern = cn.replace(/[\u4e00-\u9fff]/g, "?");
      if (pattern !== cn && out.includes(`"${pattern}"`)) {
        out = out.split(`"${pattern}"`).join(`"${cn}"`);
        changed = true;
      }
    }
  }

  return { text: out, changed };
}

function repairFile(abs) {
  const rel = toRepoRel(abs);
  let output = fs.readFileSync(abs, "utf8");
  const head = gitHead(rel);
  let action = "ok";

  if (head && hasCorruptStrings(output)) {
    const fix = repairCorruptStrings(output, head);
    if (fix.changed) {
      output = fix.text;
      action = "fixed corrupt strings";
    }
  }

  output = applyBrandTokens(output);
  const before = fs.readFileSync(abs, "utf8");

  if (output !== before) {
    fs.writeFileSync(abs, output, { encoding: "utf8" });
  }

  return { rel, action };
}

const files = walk(FRONTEND);
const results = files.map(repairFile);
const changed = results.filter((r) => r.action !== "ok");

console.log(`Scanned ${files.length} files, patched ${changed.length}`);
for (const r of changed) {
  console.log(`  ${r.action.padEnd(24)} ${r.rel}`);
}

require("./fix-chatbox-encoding.js");
console.log("Done.");
