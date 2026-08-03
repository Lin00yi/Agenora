import { afterEach, describe, expect, it, vi } from "vitest";

import { changePassword, deleteAccount, updateProfile } from "@/lib/auth";

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

function mockJsonResponse(status: number, body: unknown) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      })
    );
}

describe("auth API error messages", () => {
  it("localizes profile validation errors", async () => {
    mockJsonResponse(422, {
      detail: [{ loc: ["body", "display_name"], msg: "String should have at least 1 character" }],
    });

    await expect(updateProfile("")).rejects.toThrow("昵称");
  });

  it("localizes password and account failures", async () => {
    mockJsonResponse(400, { detail: "incorrect old password" });
    await expect(changePassword("old", "new-password")).rejects.toThrow("旧密码不正确");

    vi.restoreAllMocks();
    mockJsonResponse(404, { detail: "user not found" });
    await expect(deleteAccount()).rejects.toThrow("未找到当前账号");
  });
});
