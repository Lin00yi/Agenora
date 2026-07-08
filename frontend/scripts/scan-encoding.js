const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const ROOT = path.join(__dirname, "..");
const REPO = path.join(ROOT, "..");

function walk(dir, acc = []) {
  for (const name of fs.readdirSync(dir)) {
    if (name === "node_modules" || name === ".next") continue;
    const p = path.join(dir, name);
    const st = fs.statSync(p);
    if (st.isDirectory()) walk(p, acc);
    else if (/\.(tsx?|jsx?)$/.test(name)) acc.push(p);
  }
  return acc;
}

function countChinese(s) {
  return (s.match(/[\u4e00-\u9fff]/g) || []).length;
}

function hasCorruption(s) {
  return (
    s.includes("????") ||
    s.includes("\uFFFD") ||
    /[\u0080-\u009f]/.test(s) ||
    /\?\? \?/.test(s)
  );
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

const files = walk(ROOT);
const issues = [];

for (const abs of files) {
  const rel = path.relative(REPO, abs).replace(/\\/g, "/");
  let cur;
  try {
    cur = fs.readFileSync(abs, "utf8");
  } catch (e) {
    issues.push({ rel, problem: "invalid UTF-8: " + e.message });
    continue;
  }

  if (hasCorruption(cur)) {
    issues.push({ rel, problem: "corruption markers in working tree" });
    continue;
  }

  const head = gitHead(rel);
  if (!head) continue;

  const curCn = countChinese(cur);
  const headCn = countChinese(head);
  if (headCn > 0 && curCn < headCn * 0.5) {
    issues.push({
      rel,
      problem: `Chinese chars dropped: HEAD=${headCn}, current=${curCn}`,
    });
  }
}

console.log(JSON.stringify(issues, null, 2));
console.log(`\nScanned ${files.length} files, ${issues.length} issues`);
