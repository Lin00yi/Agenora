/**
 * Capture full-page screenshots of key routes for visual QA.
 * Usage: node scripts/ui-qa-screenshots.mjs
 */
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.resolve(
  __dirname,
  process.env.UI_QA_OUT_DIR || "../ui-qa-screenshots",
);
const BASE = process.env.UI_QA_BASE_URL || "http://localhost:3000";
const API = process.env.UI_QA_API_URL || "http://localhost:8000";
const EMAIL = process.env.UI_QA_EMAIL || "uiqa@example.com";
const PASSWORD = process.env.UI_QA_PASSWORD || "password123";

const PUBLIC_ROUTES = [
  { name: "welcome", path: "/welcome" },
  { name: "login", path: "/login" },
  { name: "register", path: "/register" },
];

const AUTH_ROUTES = [
  { name: "home-chat", path: "/" },
  { name: "chat-draft", path: "/c" },
  { name: "kbs", path: "/kbs" },
  { name: "settings", path: "/settings" },
  { name: "memories", path: "/memories" },
  { name: "admin", path: "/admin" },
  { name: "admin-users", path: "/admin/users" },
  { name: "admin-kbs", path: "/admin/kbs" },
];

fs.mkdirSync(OUT_DIR, { recursive: true });

async function apiJson(url, opts = {}) {
  const res = await fetch(url, opts);
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    throw new Error(`${opts.method || "GET"} ${url} -> ${res.status}: ${text}`);
  }
  return data;
}

async function loginViaApi() {
  try {
    return await apiJson(`${API}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
    });
  } catch {
    return await apiJson(`${API}/api/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: EMAIL,
        password: PASSWORD,
        display_name: "UI QA",
      }),
    });
  }
}

async function shot(page, name, mode) {
  const file = path.join(OUT_DIR, `${name}__${mode}.png`);
  await page.waitForTimeout(600);
  await page.screenshot({ path: file, fullPage: true });
  console.log(`saved ${file}`);
  return file;
}

async function captureRoute(context, route, mode, auth) {
  const page = await context.newPage();
  page.setDefaultTimeout(20000);
  const consoleErrors = [];
  page.on("pageerror", (err) => consoleErrors.push(String(err)));
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });

  if (auth) {
    await page.addInitScript(
      ([token, user]) => {
        localStorage.setItem("agenora:token", token);
        localStorage.setItem("agenora:user", JSON.stringify(user));
      },
      [auth.token, auth.user],
    );
  }

  await page.emulateMedia({ colorScheme: mode === "dark" ? "dark" : "light" });
  if (mode === "dark") {
    await page.addInitScript(() => {
      localStorage.setItem("agenora:theme", "dark");
      document.documentElement.classList.add("dark");
    });
  } else {
    await page.addInitScript(() => {
      localStorage.setItem("agenora:theme", "light");
      document.documentElement.classList.remove("dark");
    });
  }

  const url = `${BASE}${route.path}`;
  let status = "ok";
  let finalUrl = url;
  try {
    const res = await page.goto(url, { waitUntil: "networkidle" });
    finalUrl = page.url();
    if (res && res.status() >= 400) status = `http_${res.status()}`;
    // Prefer settled UI over loaders
    await page.waitForTimeout(900);
    await shot(page, route.name, mode);
  } catch (err) {
    status = `error: ${err.message}`;
    try {
      await shot(page, `${route.name}__FAILED`, mode);
    } catch {
      /* ignore */
    }
  }

  const meta = {
    name: route.name,
    path: route.path,
    mode,
    status,
    finalUrl,
    consoleErrors: consoleErrors.slice(0, 20),
  };
  await page.close();
  return meta;
}

async function main() {
  const auth = await loginViaApi();
  console.log(`auth as ${auth.user.email} admin=${auth.user.is_admin}`);

  // Discover dynamic routes
  const headers = { Authorization: `Bearer ${auth.token}` };
  const kbs = await apiJson(`${API}/api/kbs`, { headers });
  const kbList = Array.isArray(kbs) ? kbs : kbs.value || [];
  const dynamic = [];
  if (kbList[0]?.id) {
    dynamic.push({ name: "kb-detail", path: `/kbs/${kbList[0].id}` });
    try {
      const docs = await apiJson(`${API}/api/kbs/${kbList[0].id}/documents`, {
        headers,
      });
      const docList = Array.isArray(docs) ? docs : docs.value || [];
      if (docList[0]?.id) {
        dynamic.push({
          name: "kb-document",
          path: `/kbs/${kbList[0].id}/documents/${docList[0].id}`,
        });
      }
    } catch (err) {
      console.warn("documents lookup skipped:", err.message);
    }
  }

  try {
    const convs = await apiJson(`${API}/api/conversations`, { headers });
    const convList = Array.isArray(convs) ? convs : convs.value || [];
    if (convList[0]?.id) {
      dynamic.push({ name: "chat-id", path: `/c/${convList[0].id}` });
    }
  } catch (err) {
    console.warn("conversations lookup skipped:", err.message);
  }

  // Invite page without a real token (expect error/empty state UI)
  dynamic.push({ name: "invite-invalid", path: "/invite/ui-qa-invalid-token" });

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
  });

  const report = [];
  for (const mode of ["light", "dark"]) {
    for (const route of PUBLIC_ROUTES) {
      report.push(await captureRoute(context, route, mode, null));
    }
    for (const route of [...AUTH_ROUTES, ...dynamic]) {
      report.push(await captureRoute(context, route, mode, auth));
    }
  }

  // Mobile narrow check for a few key pages (fixed viewport, no device emulation quirks)
  const mobile = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 1,
  });
  for (const route of [
    { name: "welcome-mobile", path: "/welcome" },
    { name: "login-mobile", path: "/login" },
    { name: "home-chat-mobile", path: "/" },
    { name: "kbs-mobile", path: "/kbs" },
    { name: "settings-mobile", path: "/settings" },
    { name: "admin-kbs-mobile", path: "/admin/kbs" },
  ]) {
    const authNeeded =
      !route.path.startsWith("/welcome") && !route.path.startsWith("/login");
    report.push(
      await captureRoute(mobile, route, "light", authNeeded ? auth : null),
    );
  }

  await browser.close();

  const reportPath = path.join(OUT_DIR, "report.json");
  fs.writeFileSync(reportPath, JSON.stringify({ generatedAt: new Date().toISOString(), report }, null, 2));
  console.log(`report ${reportPath}`);
  const bad = report.filter((r) => r.status !== "ok" || r.consoleErrors.length);
  console.log(`done: ${report.length} shots, issues=${bad.length}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
