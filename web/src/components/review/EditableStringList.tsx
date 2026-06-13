import { Input, Button } from 'antd';
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons';

const { TextArea } = Input;

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
        <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 4, width: '100%' }}>
          <TextArea
            value={item}
            onChange={(e) => handleChange(i, e.target.value)}
            placeholder={placeholder}
            autoSize={{ minRows: 1, maxRows: 6 }}
            style={{ flex: 1 }}
          />
          <Button
            type="text"
            danger
            size="small"
            icon={<DeleteOutlined />}
            onClick={() => handleRemove(i)}
          />
        </div>
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
