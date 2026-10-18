import { describe, expect, it } from "vitest";
import { pageFromPath } from "../src/routes";

describe("pageFromPath", () => {
  it("maps app paths", () => {
    expect(pageFromPath("/")).toBe("portal");
    expect(pageFromPath("/index.html")).toBe("portal");
    expect(pageFromPath("/app")).toBe("console");
    expect(pageFromPath("/app/")).toBe("console");
    expect(pageFromPath("/app/index.html")).toBe("console");
    expect(pageFromPath("/charts")).toBe("charts");
    expect(pageFromPath("/chain/")).toBe("chain");
    expect(pageFromPath("/combo/index.html")).toBe("combo");
    expect(pageFromPath("/apps")).toBe("unknown");
    expect(pageFromPath("/nope")).toBe("unknown");
  });
});
