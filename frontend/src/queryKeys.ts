/** Type-safe query key factory for TanStack React Query. */

export const queryKeys = {
  campaigns: {
    all: ["campaigns"] as const,
    detail: (name: string) => ["campaign", name] as const,
    metrics: (name: string) => ["campaign-metrics", name] as const,
  },
  queue: {
    list: (campaign: string) => ["queue", campaign] as const,
    deferStats: (campaign?: string) => ["defer-stats", campaign] as const,
  },
  contacts: {
    all: (page: number) => ["contacts", page] as const,
    detail: (id: number) => ["contact", id] as const,
    events: (id: number) => ["contact-events", id] as const,
  },
  companies: {
    all: (page: number) => ["companies", page] as const,
    detail: (id: number) => ["company", id] as const,
  },
  crm: {
    contacts: (params: Record<string, unknown>) => ["crm-contacts", params] as const,
    companies: (params: Record<string, unknown>) => ["crm-companies", params] as const,
    timeline: (id: number) => ["crm-timeline", id] as const,
  },
  deals: {
    pipeline: () => ["deal-pipeline"] as const,
    list: (params: Record<string, unknown>) => ["deals", params] as const,
    detail: (id: number) => ["deal", id] as const,
  },
  templates: {
    all: ["templates"] as const,
  },
  newsletters: {
    all: ["newsletters"] as const,
    detail: (id: number) => ["newsletter", id] as const,
  },
  replies: {
    pending: ["pending-replies"] as const,
  },
  insights: {
    analysis: (campaign: string) => ["analysis", campaign] as const,
  },
  tags: {
    all: ["tags"] as const,
  },
  inbox: {
    all: ["inbox"] as const,
  },
  stats: {
    dashboard: ["dashboard-stats"] as const,
  },
} as const;
