import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Link from "@tiptap/extension-link";
import { useState, useEffect } from "react";

interface Props {
  content: string;
  onChange: (html: string) => void;
}

export default function RichTextEditor({ content, onChange }: Props) {
  const editor = useEditor({
    extensions: [
      StarterKit,
      Link.configure({ openOnClick: false }),
    ],
    content,
    onUpdate: ({ editor }) => {
      onChange(editor.getHTML());
    },
  });

  useEffect(() => {
    if (editor && content !== editor.getHTML()) {
      editor.commands.setContent(content);
    }
  }, [content]);

  const [linkInputOpen, setLinkInputOpen] = useState(false);
  const [linkUrl, setLinkUrl] = useState("");

  if (!editor) return null;

  const btn = (active: boolean) =>
    `px-2 py-1 rounded text-sm font-medium transition-colors ${
      active ? "bg-gray-900 text-white" : "bg-white text-gray-600 hover:bg-gray-100"
    }`;

  const applyLink = () => {
    const trimmed = linkUrl.trim();
    if (trimmed) {
      editor.chain().focus().setLink({ href: trimmed }).run();
    }
    setLinkUrl("");
    setLinkInputOpen(false);
  };

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <div className="flex flex-wrap items-center gap-1 px-3 py-2 border-b border-gray-200 bg-gray-50">
        <button type="button" onClick={() => editor.chain().focus().toggleBold().run()} className={btn(editor.isActive("bold"))}>
          B
        </button>
        <button type="button" onClick={() => editor.chain().focus().toggleItalic().run()} className={btn(editor.isActive("italic"))}>
          I
        </button>
        <span className="w-px bg-gray-200 mx-1" />
        <button type="button" onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()} className={btn(editor.isActive("heading", { level: 1 }))}>
          H1
        </button>
        <button type="button" onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()} className={btn(editor.isActive("heading", { level: 2 }))}>
          H2
        </button>
        <span className="w-px bg-gray-200 mx-1" />
        <button type="button" onClick={() => editor.chain().focus().toggleBulletList().run()} className={btn(editor.isActive("bulletList"))}>
          List
        </button>
        <button type="button" onClick={() => editor.chain().focus().toggleOrderedList().run()} className={btn(editor.isActive("orderedList"))}>
          1.
        </button>
        <span className="w-px bg-gray-200 mx-1" />
        <button type="button" onClick={() => setLinkInputOpen((prev) => !prev)} className={btn(editor.isActive("link") || linkInputOpen)}>
          Link
        </button>
        {editor.isActive("link") && (
          <button type="button" onClick={() => editor.chain().focus().unsetLink().run()} className={btn(false)}>
            Unlink
          </button>
        )}
        {linkInputOpen && (
          <div className="flex items-center gap-1 ml-1">
            <input
              type="url"
              value={linkUrl}
              onChange={(e) => setLinkUrl(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); applyLink(); } if (e.key === "Escape") { setLinkInputOpen(false); setLinkUrl(""); } }}
              placeholder="https://..."
              className="w-48 px-2 py-0.5 text-sm border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
              autoFocus
            />
            <button
              type="button"
              onClick={applyLink}
              className="px-2 py-0.5 text-xs font-medium text-white bg-blue-600 rounded hover:bg-blue-700"
            >
              Apply
            </button>
          </div>
        )}
        <span className="w-px bg-gray-200 mx-1" />
        <button type="button" onClick={() => editor.chain().focus().undo().run()} className={btn(false)}>
          Undo
        </button>
        <button type="button" onClick={() => editor.chain().focus().redo().run()} className={btn(false)}>
          Redo
        </button>
      </div>
      <EditorContent
        editor={editor}
        className="prose prose-sm max-w-none px-4 py-3 min-h-[300px] focus:outline-none [&_.ProseMirror]:outline-none [&_.ProseMirror]:min-h-[280px]"
      />
    </div>
  );
}
