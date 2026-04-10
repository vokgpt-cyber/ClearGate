export type Provider = 'claude' | 'openai' | 'gemini';
export type ThinkingLevel = 'off' | 'low' | 'medium' | 'high' | 'max';

export interface ModelInfo {
  id: string;
  name: string;
  provider: Provider;
  context_window: number;
  supports_thinking: boolean;
  input_cost_per_1m: number;
  output_cost_per_1m: number;
}

export interface CostEstimate {
  input_tokens: number;
  estimated_output_tokens: number;
  estimated_thinking_tokens: number;
  input_cost_usd: number;
  output_cost_usd: number;
  thinking_cost_usd: number;
  total_cost_usd: number;
}
