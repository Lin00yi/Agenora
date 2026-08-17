import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import Select from "@/components/Select";

describe("Select", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("scrolls the menu content to the selected option when it opens", () => {
    let runOpenFrame: FrameRequestCallback | undefined;
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      runOpenFrame = callback;
      return 1;
    });
    vi.stubGlobal("cancelAnimationFrame", () => {});

    const options = Array.from({ length: 20 }, (_, index) => ({
      value: `option-${index}`,
      label: `Option ${index}`,
    }));
    render(<Select value="option-12" options={options} aria-label="Example select" />);

    fireEvent.keyDown(screen.getByRole("button", { name: "Example select" }), {
      key: "ArrowDown",
    });

    const content = document.querySelector<HTMLElement>(
      '[data-slot="dropdown-menu-content"]'
    );
    const selectedItem = content?.querySelector<HTMLElement>(
      '[data-slot="dropdown-menu-item"]:nth-child(13)'
    );
    expect(content).toBeTruthy();
    expect(selectedItem).toBeTruthy();

    Object.defineProperties(content!, {
      clientHeight: { configurable: true, value: 100 },
      scrollHeight: { configurable: true, value: 1_000 },
    });
    content!.getBoundingClientRect = () =>
      ({ top: 0, bottom: 100 } as DOMRect);
    selectedItem!.getBoundingClientRect = () =>
      ({ top: 120, bottom: 160 } as DOMRect);

    runOpenFrame?.(0);

    expect(content!.scrollTop).toBe(60);
    expect(
      selectedItem?.querySelector('[data-slot="select-item-label"]')?.className
    ).toContain("text-left");
    expect(
      selectedItem?.querySelector('[data-slot="select-item-indicator"]')?.className
    ).toContain("ml-auto");
  });
});
