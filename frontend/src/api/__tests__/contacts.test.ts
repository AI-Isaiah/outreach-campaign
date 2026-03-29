import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock the request function
vi.mock("../request", () => ({
  request: vi.fn(),
  authHeaders: vi.fn(() => ({})),
  BASE: "/api",
}));

import { request } from "../request";
import { contactsApi } from "../contacts";

const mockRequest = vi.mocked(request);

describe("contactsApi", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRequest.mockResolvedValue({ success: true });
  });

  describe("patchContact", () => {
    it("sends PATCH request with partial fields", async () => {
      await contactsApi.patchContact(42, { email: "new@test.com" });

      expect(mockRequest).toHaveBeenCalledWith("/contacts/42", {
        method: "PATCH",
        body: JSON.stringify({ email: "new@test.com" }),
      });
    });

    it("sends only changed fields, not all fields", async () => {
      await contactsApi.patchContact(42, { title: "CEO" });

      const body = JSON.parse(mockRequest.mock.calls[0][1]!.body as string);
      expect(body).toEqual({ title: "CEO" });
      expect(body).not.toHaveProperty("email");
      expect(body).not.toHaveProperty("first_name");
    });

    it("sends multiple fields together", async () => {
      await contactsApi.patchContact(42, {
        first_name: "Alice",
        last_name: "Smith",
        email: "alice@test.com",
      });

      const body = JSON.parse(mockRequest.mock.calls[0][1]!.body as string);
      expect(body).toEqual({
        first_name: "Alice",
        last_name: "Smith",
        email: "alice@test.com",
      });
    });

    it("sends phone_number via PATCH", async () => {
      await contactsApi.patchContact(7, { phone_number: "+1234567890" });

      expect(mockRequest).toHaveBeenCalledWith("/contacts/7", {
        method: "PATCH",
        body: JSON.stringify({ phone_number: "+1234567890" }),
      });
    });
  });

});
