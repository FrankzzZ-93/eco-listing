import { useState } from 'react';
import { Button, Tooltip } from 'antd';
import { CopyOutlined, CheckOutlined } from '@ant-design/icons';

interface Props {
  text: string;
  size?: 'small' | 'middle' | 'large';
}

export default function CopyButton({ text, size = 'small' }: Props) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Tooltip title={copied ? '已复制' : '复制'}>
      <Button
        size={size}
        type="text"
        icon={copied ? <CheckOutlined style={{ color: '#52c41a' }} /> : <CopyOutlined />}
        onClick={handleCopy}
      />
    </Tooltip>
  );
}
