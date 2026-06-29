import type { ThemeConfig } from 'antd';

// Central Ant Design theme. Refines the default look (radius, spacing, layout
// surfaces, soft elevation) so every page inherits a consistent, polished feel
// instead of relying on per-component inline styles.
export const theme: ThemeConfig = {
  token: {
    colorPrimary: '#1677ff',
    borderRadius: 8,
    fontSize: 14,
    colorBgLayout: '#f4f6f9',
    colorTextHeading: '#1f2329',
    colorBorderSecondary: '#eef0f3',
    wireframe: false,
  },
  components: {
    Layout: {
      headerBg: '#ffffff',
      headerHeight: 56,
      headerPadding: '0 24px',
      bodyBg: '#f4f6f9',
    },
    Card: {
      borderRadiusLG: 12,
      headerFontSize: 15,
      headerBg: 'transparent',
      colorBorderSecondary: '#eef0f3',
    },
    Button: {
      controlHeight: 34,
      fontWeight: 500,
      primaryShadow: 'none',
      defaultShadow: 'none',
    },
    Input: { controlHeight: 34 },
    Select: { controlHeight: 34 },
    Table: { borderRadiusLG: 12, headerBg: '#fafbfc' },
    Segmented: { borderRadius: 8 },
    Tag: { borderRadiusSM: 6 },
    Modal: { borderRadiusLG: 12 },
    Steps: { borderRadius: 8 },
  },
};
