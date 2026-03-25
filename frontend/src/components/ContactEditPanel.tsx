import type { ContactEditState } from "../hooks/useContactEdit";

export default function ContactEditPanel({ edit }: { edit: ContactEditState }) {
  if (!edit.showEdit) return null;

  return (
    <div className="px-5 py-3 bg-gray-50 border-b border-gray-200 space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
            First Name
          </label>
          <input
            type="text"
            value={edit.editFirst}
            onChange={(e) => edit.setEditFirst(e.target.value)}
            className="w-full px-2.5 py-1.5 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
            Last Name
          </label>
          <input
            type="text"
            value={edit.editLast}
            onChange={(e) => edit.setEditLast(e.target.value)}
            className="w-full px-2.5 py-1.5 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">
          LinkedIn URL
        </label>
        <input
          type="url"
          value={edit.editLinkedIn}
          onChange={(e) => edit.setEditLinkedIn(e.target.value)}
          placeholder="https://linkedin.com/in/..."
          className="w-full px-2.5 py-1.5 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={edit.handleSaveEdit}
          disabled={edit.isSaving}
          className="px-3 py-1.5 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
        >
          {edit.isSaving ? "Saving..." : "Save"}
        </button>
        <button
          onClick={edit.handleCancelEdit}
          disabled={edit.isSaving}
          className="px-3 py-1.5 bg-white border border-gray-200 text-gray-700 rounded text-sm font-medium hover:bg-gray-50 disabled:opacity-50 transition-colors"
        >
          Cancel
        </button>
        {edit.editError && (
          <span className="text-red-500 text-xs">
            {edit.editError.message}
          </span>
        )}
      </div>
    </div>
  );
}
