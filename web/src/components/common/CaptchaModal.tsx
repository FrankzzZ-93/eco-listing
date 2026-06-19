import { useEffect, useState } from 'react';
import { Modal, Input, Typography, Image, Space, Alert } from 'antd';

const { Paragraph, Text } = Typography;

interface CaptchaModalProps {
  open: boolean;
  title?: string;
  message?: string;
  imageUrl?: string;
  loading?: boolean;
  onSubmit: (answer: string) => void;
  onCancel?: () => void;
}

/**
 * Shared human-verification modal. Shown whenever the backend parks on a
 * captcha / login challenge (run scraping or account login). Renders the
 * challenge screenshot captured by browser-act and collects the user's answer.
 */
export default function CaptchaModal({
  open,
  title = '完成人机验证',
  message,
  imageUrl,
  loading = false,
  onSubmit,
  onCancel,
}: CaptchaModalProps) {
  const [answer, setAnswer] = useState('');

  // Reset the field whenever the modal (re)opens or a new challenge image loads.
  useEffect(() => {
    if (open) setAnswer('');
  }, [open, imageUrl]);

  // Cache-bust: the screenshot can be re-written to the same path on retry.
  const src = imageUrl ? `${imageUrl}${imageUrl.includes('?') ? '&' : '?'}t=${Date.now()}` : '';

  const submit = () => {
    if (!answer.trim()) return;
    onSubmit(answer.trim());
  };

  return (
    <Modal
      open={open}
      title={title}
      onOk={submit}
      onCancel={onCancel}
      okText="提交验证"
      cancelText="稍后"
      confirmLoading={loading}
      maskClosable={false}
      okButtonProps={{ disabled: !answer.trim() }}
      destroyOnClose
    >
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        {message && (
          <Alert type="warning" showIcon message={message} />
        )}
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          抓取过程中遇到了人机验证。请根据下方截图输入验证码 / 验证信息，提交后系统会自动继续执行。
        </Paragraph>
        {src ? (
          <Image
            src={src}
            alt="验证截图"
            style={{ maxWidth: '100%', border: '1px solid #f0f0f0', borderRadius: 6 }}
            fallback=""
          />
        ) : (
          <Text type="secondary">（无验证截图，可直接在浏览器窗口中查看后输入）</Text>
        )}
        <Input
          autoFocus
          placeholder="在此输入验证码 / 验证信息"
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          onPressEnter={submit}
        />
      </Space>
    </Modal>
  );
}
