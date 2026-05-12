import { List, Typography } from 'antd';
import { CheckCircleFilled, CloseCircleFilled } from '@ant-design/icons';
import type { VerificationItem } from '../../types/listing';

const { Text } = Typography;

interface Props {
  items: VerificationItem[];
}

export default function VerificationChecklist({ items }: Props) {
  return (
    <List
      size="small"
      header={<Text strong>Verification Checklist</Text>}
      bordered
      dataSource={items}
      renderItem={(item) => (
        <List.Item>
          {item.passed ? (
            <CheckCircleFilled style={{ color: '#52c41a', marginRight: 8 }} />
          ) : (
            <CloseCircleFilled style={{ color: '#ff4d4f', marginRight: 8 }} />
          )}
          <Text>{item.label}</Text>
          <Text type="secondary" style={{ marginLeft: 'auto', fontSize: 12 }}>
            {item.detail}
          </Text>
        </List.Item>
      )}
    />
  );
}
