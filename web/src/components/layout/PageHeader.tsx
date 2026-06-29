import type { ReactNode } from 'react';
import { Typography } from 'antd';

const { Title, Paragraph } = Typography;

interface Props {
  title: ReactNode;
  subtitle?: ReactNode;
  icon?: ReactNode;
  extra?: ReactNode;
}

/** Consistent page header: title (+ optional icon), subtitle, and right-aligned
 *  actions. Unifies the per-page `<Title>` + `<Paragraph>` intros. */
export default function PageHeader({ title, subtitle, icon, extra }: Props) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, marginBottom: 20 }}>
      <div style={{ minWidth: 0 }}>
        <Title level={3} style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
          {icon}
          {title}
        </Title>
        {subtitle && (
          <Paragraph type="secondary" style={{ margin: '6px 0 0' }}>
            {subtitle}
          </Paragraph>
        )}
      </div>
      {extra && <div style={{ flexShrink: 0 }}>{extra}</div>}
    </div>
  );
}
