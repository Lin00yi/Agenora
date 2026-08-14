import { beforeEach, describe, expect, it, vi } from "vitest";

const sonner = vi.hoisted(() => {
  const create = vi.fn(() => "sonner-id");
  return {
    message: create,
    success: create,
    info: create,
    warning: create,
    error: create,
    loading: create,
    dismiss: vi.fn(),
    custom: vi.fn(),
    promise: vi.fn(),
    getHistory: vi.fn(() => []),
  };
});

vi.mock("sonner", () => ({ toast: sonner }));

import { toast } from "./toast";

type ToastCallOptions = {
  duration?: number;
};

describe("toast queue", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    toast.dismiss();
    vi.clearAllMocks();
  });

  it("pushes the latest item into a four-item stack and evicts the oldest", () => {
    const ids = Array.from({ length: 5 }, (_, index) =>
      toast.success(`通知 ${index + 1}`, { duration: 100 })
    );

    const successCalls = sonner.success.mock.calls as unknown as Array<
      [string, ToastCallOptions]
    >;
    expect(sonner.success).toHaveBeenCalledTimes(4);
    expect(successCalls.map(([, options]) => options?.duration)).toEqual([
      Infinity,
      Infinity,
      Infinity,
      Infinity,
    ]);

    // The fifth notification enters the front of the stack immediately after
    // the oldest item has completed its exit transition.
    expect(sonner.dismiss).toHaveBeenCalledWith(ids[0]);
    vi.advanceTimersByTime(220);

    expect(sonner.success).toHaveBeenCalledTimes(5);
    expect(successCalls[4][0]).toBe("通知 5");
    expect(successCalls[4][1]?.duration).toBe(Infinity);

    vi.advanceTimersByTime(480);
    expect(sonner.dismiss).toHaveBeenLastCalledWith(ids[1]);
  });
});
