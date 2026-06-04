import React, { useState } from 'react';
// Note: lucide-react icon imports omitted due to type declaration issues in v0.542
import { SectionCard, toggle } from './FormHelpers';
import api from '../../lib/api';

export interface AIAnalystForm {
  apiKey: string;
  model: string;
  enabled: boolean;
}

interface Props {
  form: AIAnalystForm;
  onChange: (f: AIAnalystForm) => void;
}

export function AIAnalystSettings({ form, onChange }: Props) {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);

  const testConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await api.get('/api/ai/chat/status');
      if (res.data.configured) {
        setTestResult({ ok: true, message: `Connected — model: ${res.data.model}` });
      } else {
        setTestResult({ ok: false, message: 'API key not configured. Save settings first.' });
      }
    } catch {
      setTestResult({ ok: false, message: 'Could not reach backend.' });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="space-y-3">
      <SectionCard
        title="Claude API"
        description="Connect to the Claude API to enable the AI analyst chat. Your API key is stored locally on your Home Assistant instance and never sent to the browser."
      >
        <div className="space-y-4">
          <label className="block">
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">API Key</span>
            <input
              type="password"
              value={form.apiKey}
              onChange={e => onChange({ ...form, apiKey: e.target.value })}
              placeholder="sk-ant-..."
              className="mt-1 block w-full rounded-lg border bg-white dark:bg-gray-700 border-gray-300 dark:border-gray-600 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
              Get your key at{' '}
              <span className="font-mono">console.anthropic.com</span>
            </p>
          </label>

          <label className="block">
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Model</span>
            <select
              value={form.model}
              onChange={e => onChange({ ...form, model: e.target.value })}
              className="mt-1 block w-full rounded-lg border bg-white dark:bg-gray-700 border-gray-300 dark:border-gray-600 text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="claude-sonnet-4-20250514">Claude Sonnet 4 (fast, recommended)</option>
              <option value="claude-opus-4-20250514">Claude Opus 4 (deeper analysis, slower)</option>
            </select>
          </label>

          {toggle('Enable AI Analyst', form.enabled, v => onChange({ ...form, enabled: v }))}

          <div className="flex items-center gap-3">
            <button
              onClick={testConnection}
              disabled={testing}
              className="px-4 py-1.5 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 font-medium text-xs disabled:opacity-40 flex items-center gap-1.5"
            >
              {testing
                ? <div className="h-3 w-3 border-2 border-gray-500 rounded-full border-t-transparent animate-spin" />
                : null}
              <span>Test Connection</span>
            </button>
            {testResult && (
              <span className={`text-xs flex items-center gap-1 ${testResult.ok ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                <span className={`inline-block h-2 w-2 rounded-full ${testResult.ok ? 'bg-green-500' : 'bg-red-500'}`} />
                {testResult.message}
              </span>
            )}
          </div>
        </div>
      </SectionCard>
    </div>
  );
}
