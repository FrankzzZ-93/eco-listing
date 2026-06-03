import { Input, Button, Space } from 'antd';
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons';

interface Props {
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
}

export default function EditableStringList({ value, onChange, placeholder }: Props) {
  const handleChange = (index: number, text: string) => {
    const next = [...value];
    next[index] = text;
    onChange(next);
  };

  const handleAdd = () => onChange([...value, '']);

  const handleRemove = (index: number) => onChange(value.filter((_, i) => i !== index));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {value.map((item, i) => (
        <Space key={i} style={{ width: '100%' }} align="start">
          <Input
            value={item}
            onChange={(e) => handleChange(i, e.target.value)}
            placeholder={placeholder}
            style={{ width: 480 }}
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
