import { describe, expect, it } from "vitest";
import { pageFromPath } from "../src/routes";

describe("pageFromPath", () => {
  it("maps app paths", () => {
    expect(pageFromPath("/")).toBe("console");
    expect(pageFromPath("/charts")).toBe("charts");
    expect(pageFromPath("/chain/")).toBe("chain");
    expect(pageFromPath("/combo/index.html")).toBe("combo");
    expect(pageFromPath("/nope")).toBe("unknown");
  });
});
