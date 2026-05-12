import { useState } from 'react';
import {
  Card,
  Form,
  Input,
  Select,
  Button,
  Upload,
  Space,
  Typography,
  message,
  Divider,
  Row,
  Col,
  Tag,
  Steps,
} from 'antd';
import {
  PlusOutlined,
  MinusCircleOutlined,
  InboxOutlined,
  FileTextOutlined,
  SearchOutlined,
  TagsOutlined,
  EditOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { createRun } from '../api/runs';
import { isValidAsin, normalizeAsin } from '../utils/asinValidator';

const { Dragger } = Upload;
const { Title, Text, Paragraph } = Typography;

const SITES = [
  { value: 'amazon.com.au', label: 'Amazon AU (amazon.com.au)' },
  { value: 'amazon.com', label: 'Amazon US (amazon.com)' },
  { value: 'amazon.co.uk', label: 'Amazon UK (amazon.co.uk)' },
  { value: 'amazon.de', label: 'Amazon DE (amazon.de)' },
  { value: 'amazon.co.jp', label: 'Amazon JP (amazon.co.jp)' },
];

interface FormValues {
  site: string;
  product_name: string;
  competitor_asins: { asin: string }[];
}

interface FileInputProps {
  label: string;
  hint: string;
  required?: boolean;
  file: File | null;
  onFileChange: (file: File | null) => void;
}

function FileInput({ label, hint, required, file, onFileChange }: FileInputProps) {
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ marginBottom: 6 }}>
        <Text strong>{label}</Text>
        {required && <Text type="danger"> *</Text>}
        {!required && <Tag style={{ marginLeft: 8 }} color="default">可选</Tag>}
      </div>
      <Dragger
        accept=".csv,.json,.txt,.md,.xlsx"
        maxCount={1}
        beforeUpload={(f) => {
          onFileChange(f);
          return false;
        }}
        onRemove={() => {
          onFileChange(null);
        }}
        fileList={file ? [{ uid: '-1', name: file.name, status: 'done' as const }] : []}
        style={{ padding: '8px 0' }}
      >
        <p className="ant-upload-drag-icon" style={{ marginBottom: 4 }}>
          <InboxOutlined style={{ fontSize: 28, color: '#1677ff' }} />
        </p>
        <p className="ant-upload-text" style={{ fontSize: 13, margin: 0 }}>
          点击或拖拽文件到此处
        </p>
        <p className="ant-upload-hint" style={{ fontSize: 12 }}>
          {hint}
        </p>
      </Dragger>
    </div>
  );
}

const WORKFLOW_STEPS = [
  {
    title: '认知层',
    description: '竞品抓取 → 评论分析 → Rufus 问答 → 本品属性表',
    icon: <SearchOutlined />,
  },
  {
    title: '语义层',
    description: '关键词分类建模',
    icon: <TagsOutlined />,
  },
  {
    title: '表达层',
    description: '多轮迭代生成 Listing + ST 优化',
    icon: <EditOutlined />,
  },
];

export default function InputPage() {
  const [form] = Form.useForm<FormValues>();
  const [loading, setLoading] = useState(false);
  const [keywordFile, setKeywordFile] = useState<File | null>(null);
  const [competitorListingFile, setCompetitorListingFile] = useState<File | null>(null);
  const [productAttributesFile, setProductAttributesFile] = useState<File | null>(null);
  const navigate = useNavigate();

  const handleSubmit = async (values: FormValues) => {
    if (!keywordFile) {
      message.warning('请上传关键词词库文件');
      return;
    }

    const competitorAsins = values.competitor_asins
      .map((item) => normalizeAsin(item.asin))
      .filter(Boolean);

    if (competitorAsins.length < 1) {
      message.warning('请至少填写 1 个竞品 ASIN');
      return;
    }

    setLoading(true);
    try {
      const res = await createRun({
        product_name: values.product_name?.trim() || '',
        competitor_asins: competitorAsins,
        site: values.site,
      });
      message.success('任务创建成功');
      navigate(`/run/${res.run_id}`);
    } catch (err) {
      message.error('任务创建失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 720, margin: '0 auto', paddingTop: 40 }}>
      <Card>
        <Title level={3} style={{ textAlign: 'center', marginBottom: 8 }}>
          Eco Listing 生成器
        </Title>
        <Paragraph
          type="secondary"
          style={{ textAlign: 'center', marginBottom: 24 }}
        >
          输入竞品信息和关键词词库，自动生成高质量亚马逊 Listing
        </Paragraph>

        <Steps
          size="small"
          items={WORKFLOW_STEPS}
          style={{ marginBottom: 32, padding: '0 24px' }}
        />

        <Form
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
          initialValues={{
            site: 'amazon.com.au',
            competitor_asins: [{ asin: '' }],
          }}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="site"
                label="站点"
                rules={[{ required: true, message: '请选择站点' }]}
              >
                <Select options={SITES} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="product_name"
                label="产品名称"
                tooltip="给本次任务起个名字，方便辨认（选填）"
              >
                <Input placeholder="如：无线蓝牙耳机、瑜伽垫 等" />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            label="竞品 ASIN"
            tooltip="输入 1~10 个竞品的 Amazon ASIN，系统将自动抓取其 Listing、评论和 Rufus 问答"
            required
          >
            <Form.List
              name="competitor_asins"
              rules={[
                {
                  validator: async (_, items) => {
                    if (!items || items.length < 1) {
                      return Promise.reject('至少需要 1 个竞品 ASIN');
                    }
                  },
                },
              ]}
            >
              {(fields, { add, remove }, { errors }) => (
                <>
                  {fields.map((field) => (
                    <Space
                      key={field.key}
                      style={{ display: 'flex', marginBottom: 8 }}
                      align="baseline"
                    >
                      <Form.Item
                        {...field}
                        name={[field.name, 'asin']}
                        rules={[
                          { required: true, message: '请填写 ASIN' },
                          {
                            validator: (_, value) =>
                              !value || isValidAsin(value)
                                ? Promise.resolve()
                                : Promise.reject('ASIN 格式不正确'),
                          },
                        ]}
                        style={{ marginBottom: 0 }}
                      >
                        <Input
                          placeholder="B0XXXXXXXXXX"
                          style={{ width: 280, textTransform: 'uppercase' }}
                        />
                      </Form.Item>
                      {fields.length > 1 && (
                        <MinusCircleOutlined onClick={() => remove(field.name)} />
                      )}
                    </Space>
                  ))}
                  {fields.length < 10 && (
                    <Button
                      type="dashed"
                      onClick={() => add({ asin: '' })}
                      icon={<PlusOutlined />}
                      style={{ width: 280 }}
                    >
                      添加竞品 ASIN
                    </Button>
                  )}
                  <Form.ErrorList errors={errors} />
                </>
              )}
            </Form.List>
          </Form.Item>

          <Divider orientation="left">
            <Space>
              <FileTextOutlined />
              <span>上传文件</span>
            </Space>
          </Divider>

          <Row gutter={16}>
            <Col span={8}>
              <FileInput
                label="关键词词库"
                hint="鸥鹭出单词报告等"
                required
                file={keywordFile}
                onFileChange={setKeywordFile}
              />
            </Col>
            <Col span={8}>
              <FileInput
                label="竞品 Listing 文本"
                hint="不上传则自动抓取"
                file={competitorListingFile}
                onFileChange={setCompetitorListingFile}
              />
            </Col>
            <Col span={8}>
              <FileInput
                label="本品属性表"
                hint="已有则跳过认知层分析"
                file={productAttributesFile}
                onFileChange={setProductAttributesFile}
              />
            </Col>
          </Row>

          <Form.Item style={{ textAlign: 'center', marginTop: 24 }}>
            <Button
              type="primary"
              htmlType="submit"
              size="large"
              loading={loading}
              style={{ width: 200 }}
            >
              开始生成
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
