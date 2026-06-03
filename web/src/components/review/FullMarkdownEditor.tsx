import { Modal } from 'antd';
import Editor from '@monaco-editor/react';

interface Props {
  open: boolean;
  content: string;
  onSave: (content: string) => void;
  onClose: () => void;
}

export default function FullMarkdownEditor({ open, content, onSave, onClose }: Props) {
  let editorValue = content;

  return (
    <Modal
      title="全文编辑"
      open={open}
      onOk={() => onSave(editorValue)}
      onCancel={onClose}
      width={800}
      okText="保存修改"
      cancelText="取消"
    >
      <div style={{ height: 500, border: '1px solid #d9d9d9', borderRadius: 6 }}>
        <Editor
          height="100%"
          defaultLanguage="markdown"
          defaultValue={content}
          onChange={(val) => {
            editorValue = val ?? '';
          }}
          options={{
            minimap: { enabled: false },
            wordWrap: 'on',
            fontSize: 13,
          }}
        />
      </div>
    </Modal>
  );
}
