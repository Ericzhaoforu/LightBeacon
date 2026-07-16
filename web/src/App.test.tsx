import { describe, expect, it } from "vitest";

import { rectangleSelection } from "./App";

describe("grid selection", () => {
  it("selects a rectangular range", () => {
    const selected = rectangleSelection(
      { anchor: 1, current: 10, base: new Set<number>() },
      4,
    );
    expect(Array.from(selected).sort((a, b) => a - b)).toEqual([1, 2, 5, 6, 9, 10]);
  });

  it("preserves ctrl selection", () => {
    const selected = rectangleSelection(
      { anchor: 0, current: 0, base: new Set([7]) },
      4,
    );
    expect(Array.from(selected).sort((a, b) => a - b)).toEqual([0, 7]);
  });
});

