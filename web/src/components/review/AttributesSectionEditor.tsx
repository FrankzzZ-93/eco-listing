import { useState } from 'react';
import { Input, Button, Space } from 'antd';
import { EditOutlined, CheckOutlined, CloseOutlined } from '@ant-design/icons';

const { TextArea } = Input;

interface Props {
  label: string;
  value: string;
  onChange: (newValue: string) => void;
}

export default function AttributesSectionEditor({ label, value, onChange }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  const handleSave = () => {
    onChange(draft);
    setEditing(false);
  };

  const handleCancel = () => {
    setDraft(value);
    setEditing(false);
  };

  if (editing) {
    return (
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontWeight: 500, marginBottom: 4 }}>{label}</div>
        <TextArea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          autoSize={{ minRows: 2, maxRows: 8 }}
        />
        <Space style={{ marginTop: 8 }}>
          <Button size="small" icon={<CheckOutlined />} type="primary" onClick={handleSave}>
            保存
          </Button>
          <Button size="small" icon={<CloseOutlined />} onClick={handleCancel}>
            取消
          </Button>
        </Space>
      </div>
    );
  }

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontWeight: 500, marginBottom: 4 }}>
        {label}
        <Button
          type="link"
          size="small"
          icon={<EditOutlined />}
          onClick={() => setEditing(true)}
          style={{ marginLeft: 8 }}
        >
          编辑
        </Button>
      </div>
      <div style={{ whiteSpace: 'pre-wrap', color: '#595959', paddingLeft: 8 }}>
        {value || <em style={{ color: '#bfbfbf' }}>暂无内容</em>}
      </div>
    </div>
  );
}
