// Render the canonical product-attribute object as human-readable Markdown.
//
// The schema keys are English (basic_info / market_analysis / copywriting_ref,
// see prompts/product_analyst/info_fusion_v2.md); this maps the known ones to
// Chinese labels and falls back to a generic recursive renderer for anything
// unexpected, so export never throws on a non-standard shape.

const LABELS: Record<string, string> = {
  basic_info: '基础产品信息',
  market_analysis: '竞品市场分析',
  copywriting_ref: '文案优化参考',
  product_name: '产品名称',
  core_category_word: '核心品类词',
  key_identifiers: '关键识别词',
  product_dimensions: '产品尺寸',
  package_dimensions: '包装尺寸',
  size: '尺寸',
  weight: '重量',
  material: '材质',
  color_spec_quantity: '颜色/规格/数量',
  colors: '颜色',
  specs: '规格',
  package_quantity: '包装数量',
  applicable: '适用范围',
  target_users: '目标用户',
  use_cases: '使用场景',
  compatible_devices: '兼容设备',
  not_applicable: '不适用场景',
  features: '功能特性',
  package_contents: '包装内容',
  certifications: '认证',
  warranty: '保修',
  alex_concerns: 'Alex 买家关注点',
  rufus_concerns: 'Alex 买家关注点',
  market_standard: '市场标配',
  differentiation: '差异化优势',
  known_pain_points: '已知痛点',
  prohibited_info: '禁用信息',
  core_highlights: '核心亮点',
  tech_term_conversion: '术语转化',
  question: '问题',
  answer: '回答',
  pain_point: '痛点',
  source: '来源',
  content: '内容',
  reason: '原因',
  highlight: '亮点',
  original: '技术词',
  converted: '大白话',
};

function label(key: string): string {
  return LABELS[key] ?? key;
}

function render(value: unknown, depth: number): string {
  const pad = '  '.repeat(Math.max(0, depth - 2));
  if (value === null || value === undefined || value === '') return '';
  if (typeof value !== 'object') return String(value);

  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (item && typeof item === 'object') {
          const parts = Object.entries(item as Record<string, unknown>)
            .filter(([, v]) => v !== null && v !== undefined && v !== '')
            .map(([k, v]) => `${label(k)}：${render(v, depth + 1)}`);
          return `${pad}- ${parts.join('；')}`;
        }
        return `${pad}- ${String(item)}`;
      })
      .filter(Boolean)
      .join('\n');
  }

  const entries = Object.entries(value as Record<string, unknown>).filter(
    ([, v]) => v !== null && v !== undefined && v !== '',
  );
  return entries
    .map(([k, v]) => {
      const rendered = render(v, depth + 1);
      if (!rendered) return '';
      if (typeof v === 'object') {
        const heading = '#'.repeat(Math.min(depth, 6));
        return `${heading} ${label(k)}\n\n${rendered}`;
      }
      return `${pad}- **${label(k)}**：${rendered}`;
    })
    .filter(Boolean)
    .join('\n\n');
}

export function attributesToMarkdown(data: Record<string, unknown>): string {
  return `# 本品属性表\n\n${render(data, 2)}\n`;
}
