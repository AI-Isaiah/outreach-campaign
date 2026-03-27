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
  });

  describe("updatePhone", () => {
    it("sends POST to phone endpoint", async () => {
      await contactsApi.updatePhone(7, "+1234567890");

      expect(mockRequest).toHaveBeenCalledWith("/contacts/7/phone", {
        method: "POST",
        body: JSON.stringify({ phone_number: "+1234567890" }),
      });
    });
  });

  describe("updateLinkedInUrl", () => {
    it("sends POST to linkedin-url endpoint", async () => {
      await contactsApi.updateLinkedInUrl(7, "https://linkedin.com/in/alice");

      expect(mockRequest).toHaveBeenCalledWith("/contacts/7/linkedin-url", {
        method: "POST",
        body: JSON.stringify({ linkedin_url: "https://linkedin.com/in/alice" }),
      });
    });
  });

  describe("updateContactName", () => {
    it("sends POST with first and last name", async () => {
      await contactsApi.updateContactName(7, "Alice", "Smith");

      expect(mockRequest).toHaveBeenCalledWith("/contacts/7/name", {
        method: "POST",
        body: JSON.stringify({ first_name: "Alice", last_name: "Smith" }),
      });
    });
  });
});
