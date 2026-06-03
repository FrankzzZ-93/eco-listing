import { Input, Button, Space } from 'antd';
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons';

interface Props {
  value: Record<string, string>[];
  onChange: (value: Record<string, string>[]) => void;
  field1: { key: string; label: string; placeholder?: string };
  field2: { key: string; label: string; placeholder?: string };
}

export default function EditablePairList({ value, onChange, field1, field2 }: Props) {
  const handleChange = (index: number, fieldKey: string, text: string) => {
    const next = value.map((item, i) =>
      i === index ? { ...item, [fieldKey]: text } : item,
    );
    onChange(next);
  };

  const handleAdd = () =>
    onChange([...value, { [field1.key]: '', [field2.key]: '' }]);

  const handleRemove = (index: number) =>
    onChange(value.filter((_, i) => i !== index));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {value.length > 0 && (
        <div style={{ display: 'flex', gap: 8, paddingLeft: 0 }}>
          <span style={{ width: 280, fontSize: 12, color: '#8c8c8c' }}>{field1.label}</span>
          <span style={{ width: 280, fontSize: 12, color: '#8c8c8c' }}>{field2.label}</span>
        </div>
      )}
      {value.map((item, i) => (
        <Space key={i} align="start">
          <Input
            value={item[field1.key] ?? ''}
            onChange={(e) => handleChange(i, field1.key, e.target.value)}
            placeholder={field1.placeholder}
            style={{ width: 280 }}
          />
          <Input
            value={item[field2.key] ?? ''}
            onChange={(e) => handleChange(i, field2.key, e.target.value)}
            placeholder={field2.placeholder}
            style={{ width: 280 }}
          />
          <Button
            type="text"
            danger
            size="small"
            icon={<DeleteOutlined />}
            onClick={() => handleRemove(i)}
          />
        </Space>
      ))}
      <Button
        type="dashed"
        size="small"
        icon={<PlusOutlined />}
        onClick={handleAdd}
        style={{ width: 120 }}
      >
        添加
      </Button>
    </div>
  );
}
