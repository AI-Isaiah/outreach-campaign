import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Tag } from "../types";

interface Props {
  entityType: "contact" | "company";
  entityId: number;
}

export default function TagPicker({ entityType, entityId }: Props) {
  const queryClient = useQueryClient();
  const [showAdd, setShowAdd] = useState(false);
  const [newTagName, setNewTagName] = useState("");
  const [newTagColor, setNewTagColor] = useState("#6B7280");

  const { data: entityTags = [] } = useQuery({
    queryKey: ["entityTags", entityType, entityId],
    queryFn: () => api.getEntityTags(entityType, entityId),
  });

  const { data: allTags = [] } = useQuery({
    queryKey: ["tags"],
    queryFn: () => api.listTags(),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["entityTags", entityType, entityId] });
    queryClient.invalidateQueries({ queryKey: ["tags"] });
  };

  const attachMutation = useMutation({
    mutationFn: (tagId: number) => api.attachTag(tagId, entityType, entityId),
    onSuccess: invalidate,
  });

  const detachMutation = useMutation({
    mutationFn: (tagId: number) => api.detachTag(tagId, entityType, entityId),
    onSuccess: invalidate,
  });

  const createMutation = useMutation({
    mutationFn: () => api.createTag(newTagName, newTagColor),
    onSuccess: (data) => {
      invalidate();
      attachMutation.mutate(data.id);
      setNewTagName("");
      setShowAdd(false);
    },
  });

  const attachedIds = new Set(entityTags.map((t: Tag) => t.id));
  const availableTags = allTags.filter((t: Tag) => !attachedIds.has(t.id));

  const COLORS = ["#6B7280", "#EF4444", "#F59E0B", "#10B981", "#3B82F6", "#8B5CF6", "#EC4899"];

  return (
    <div className="space-y-2">
      {/* Current tags */}
      <div className="flex flex-wrap gap-1.5">
        {entityTags.map((tag: Tag) => (
          <span
            key={tag.id}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium text-white"
            style={{ backgroundColor: tag.color }}
          >
            {tag.name}
            <button
              onClick={() => detachMutation.mutate(tag.id)}
              className="hover:opacity-75 ml-0.5"
            >
              &times;
            </button>
          </span>
        ))}

        {/* Add tag dropdown */}
        <div className="relative">
          <button
            onClick={() => setShowAdd(!showAdd)}
            className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border border-dashed border-gray-300 text-gray-500 hover:border-gray-400 hover:text-gray-700"
          >
            + Tag
          </button>

          {showAdd && (
            <div className="absolute z-10 mt-1 w-52 bg-white border border-gray-200 rounded-lg shadow-lg p-2 space-y-1">
              {availableTags.length > 0 && (
                <div className="max-h-32 overflow-y-auto space-y-0.5">
                  {availableTags.map((tag: Tag) => (
                    <button
                      key={tag.id}
                      onClick={() => {
                        attachMutation.mutate(tag.id);
                        setShowAdd(false);
                      }}
                      className="w-full flex items-center gap-2 px-2 py-1 rounded text-xs hover:bg-gray-50 text-left"
                    >
                      <span
                        className="w-3 h-3 rounded-full shrink-0"
                        style={{ backgroundColor: tag.color }}
                      />
                      {tag.name}
                    </button>
                  ))}
                </div>
              )}
              <div className="border-t pt-1.5 mt-1.5 space-y-1.5">
                <input
                  type="text"
                  placeholder="New tag name..."
                  value={newTagName}
                  onChange={(e) => setNewTagName(e.target.value)}
                  className="w-full px-2 py-1 border rounded text-xs"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && newTagName.trim()) createMutation.mutate();
                  }}
                />
                <div className="flex gap-1">
                  {COLORS.map((c) => (
                    <button
                      key={c}
                      onClick={() => setNewTagColor(c)}
                      className={`w-5 h-5 rounded-full border-2 ${
                        newTagColor === c ? "border-gray-900" : "border-transparent"
                      }`}
                      style={{ backgroundColor: c }}
                    />
                  ))}
                </div>
                <button
                  onClick={() => createMutation.mutate()}
                  disabled={!newTagName.trim()}
                  className="w-full px-2 py-1 bg-gray-900 text-white rounded text-xs disabled:opacity-50"
                >
                  Create & Add
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
