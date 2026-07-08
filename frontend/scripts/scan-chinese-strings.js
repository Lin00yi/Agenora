const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const ROOT = path.join(__dirname, "..");
const REPO = path.join(ROOT, "..");

function walk(dir, acc = []) {
  for (const name of fs.readdirSync(dir)) {
    if (name === "node_modules" || name === ".next" || name === "ui") continue;
    const p = path.join(dir, name);
    const st = fs.statSync(p);
    if (st.isDirectory()) walk(p, acc);
    else if (/\.tsx$/.test(name)) acc.push(p);
  }
  return acc;
}

function gitHead(rel) {
  try {
    return execSync(`git show HEAD:${rel.replace(/\\/g, "/")}`, {
      cwd: REPO,
      encoding: "utf8",
      maxBuffer: 10 * 1024 * 1024,
    });
  } catch {
    return null;
  }
}

function extractChineseStrings(src) {
  const out = new Set();
  const re = /(["'`])((?:\\.|(?!\1)[\s\S])*?)\1/g;
  let m;
  while ((m = re.exec(src))) {
    if (/[\u4e00-\u9fff]/.test(m[2])) out.add(m[2]);
  }
  return out;
}

const files = walk(ROOT);
const missing = [];

for (const abs of files) {
  const rel = path.relative(REPO, abs).replace(/\\/g, "/");
  const head = gitHead(rel);
  if (!head) continue;
  const cur = fs.readFileSync(abs, "utf8");
  const headStrings = extractChineseStrings(head);
  const curStrings = extractChineseStrings(cur);
  for (const s of headStrings) {
    if (s.includes("????")) continue;
    const ok =
      cur.includes(s) ||
      [...curStrings].some(
        (c) => c.replace(/\s+/g, "") === s.replace(/\s+/g, "")
      );
    if (!ok) missing.push({ rel, string: s.slice(0, 60) });
  }
}

console.log(`Missing ${missing.length} Chinese strings from HEAD:\n`);
for (const x of missing.slice(0, 40)) {
  console.log(`${x.rel}: ${JSON.stringify(x.string)}`);
}
if (missing.length > 40) console.log(`... and ${missing.length - 40} more`);
