export const queryKeys = {
  campaigns: {
    all: ["campaigns"] as const,
    detail: (name: string) => ["campaign-metrics", name] as const,
  },
  contacts: {
    all: (
      page: number,
      filters: Record<string, unknown>,
      sortBy?: string,
      sortDir?: string,
    ) => ["crm-contacts", page, filters, sortBy, sortDir] as const,
    detail: (id: number) => ["contact", id] as const,
    picker: (...args: unknown[]) =>
      ["contacts", "picker", ...args] as const,
  },
  queue: {
    all: ["queue-all"] as const,
  },
  templates: {
    all: ["templates"] as const,
  },
  products: {
    all: ["products"] as const,
  },
};
