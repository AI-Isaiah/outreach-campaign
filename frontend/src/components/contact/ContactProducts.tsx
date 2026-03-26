import { useState } from "react";
import { useMutation, useQueryClient, useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { ContactProduct, Product } from "../../types";
import ProductStageBadge from "../ProductStageBadge";
import Button from "../ui/Button";
import Card from "../ui/Card";

const PRODUCT_STAGES = ["discussed", "interested", "due_diligence", "invested", "declined"];

export default function ContactProducts({ contactId }: { contactId: number }) {
  const queryClient = useQueryClient();
  const [addProductId, setAddProductId] = useState("");

  const { data: contactProducts } = useQuery<ContactProduct[]>({
    queryKey: ["contact-products", contactId],
    queryFn: () => api.listContactProducts(contactId),
    enabled: !!contactId,
  });

  const { data: allProducts } = useQuery<Product[]>({
    queryKey: ["products"],
    queryFn: () => api.listProducts(),
  });

  const linkProductMutation = useMutation({
    mutationFn: (productId: number) => api.linkContactProduct(contactId, productId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contact-products", contactId] });
      setAddProductId("");
    },
  });

  const updateProductStageMutation = useMutation({
    mutationFn: ({ productId, stage }: { productId: number; stage: string }) =>
      api.updateContactProductStage(contactId, productId, stage),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["contact-products", contactId] }),
  });

  const removeProductMutation = useMutation({
    mutationFn: (productId: number) => api.removeContactProduct(contactId, productId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["contact-products", contactId] }),
  });

  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-semibold text-gray-900">Product Interests</h2>
        <div className="flex gap-2">
          <select
            value={addProductId}
            onChange={(e) => setAddProductId(e.target.value)}
            className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">Add product...</option>
            {(allProducts || [])
              .filter((p) => !(contactProducts || []).some((cp) => cp.product_id === p.id))
              .map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
          </select>
          {addProductId && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => linkProductMutation.mutate(Number(addProductId))}
              loading={linkProductMutation.isPending}
            >
              Add
            </Button>
          )}
        </div>
      </div>

      {(contactProducts || []).length > 0 ? (
        <div className="space-y-2">
          {contactProducts!.map((cp: ContactProduct) => (
            <div key={cp.id} className="flex items-center justify-between bg-gray-50 rounded-lg p-3">
              <div>
                <span className="text-sm font-medium text-gray-900">{cp.product_name}</span>
              </div>
              <div className="flex items-center gap-2">
                <select
                  value={cp.stage}
                  onChange={(e) =>
                    updateProductStageMutation.mutate({ productId: cp.product_id, stage: e.target.value })
                  }
                  className="px-2 py-1 border border-gray-200 rounded-lg text-xs bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {PRODUCT_STAGES.map((s) => (
                    <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
                  ))}
                </select>
                <ProductStageBadge stage={cp.stage} />
                <button
                  onClick={() => removeProductMutation.mutate(cp.product_id)}
                  className="text-xs text-red-500 hover:text-red-700 font-medium"
                >
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-gray-400">No product interests tracked yet.</p>
      )}
    </Card>
  );
}
